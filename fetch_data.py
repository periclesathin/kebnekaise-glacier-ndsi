import os
from io import BytesIO
import ee
import requests
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

PROJECT_ID = os.environ.get("GEE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
if not PROJECT_ID:
    raise RuntimeError("Set the GEE_PROJECT_ID environment variable before running.")

ee.Initialize(project=PROJECT_ID)

START_YEAR = 2018
END_YEAR = 2026
BASELINE_YEAR = 2020
CS_CDF_THRESHOLD = 0.60
MIN_VALID_FRAC = 0.80
NDSI_THRESHOLD = 0.40
SHADOW_B3_THRESHOLD = 0.15
B4_ICE_SNOW_THRESHOLD = 0.45

# Kebnekaise massif (~70 km west of Kiruna)
roi_box = ee.Geometry.Rectangle([18.45, 67.87, 18.60, 67.93])

glims = (
    ee.FeatureCollection("GLIMS/current")
    .filterBounds(roi_box)
    .filter(ee.Filter.eq("line_type", "glac_bound"))
)
glacier_geom = glims.geometry().intersection(roi_box, ee.ErrorMargin(1))
glims_area_km2 = (
    ee.Image.pixelArea()
    .reduceRegion(reducer=ee.Reducer.sum(), geometry=glacier_geom, scale=20, maxPixels=1e9)
    .get("area")
    .getInfo()
) / 1e6
print(f"GLIMS glacier area in ROI: {glims_area_km2:.2f} km²")

# Late-ablation window: Aug 1 – Sep 15 (DOY 213–258)
s2 = (
    ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
    .filterBounds(glacier_geom)
    .filterDate(f"{START_YEAR}-08-01", f"{END_YEAR}-09-16")
    .filter(ee.Filter.dayOfYear(213, 258))
)
cs_plus = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
s2_linked = s2.linkCollection(cs_plus, ["cs_cdf"])


def prep_scene(img):
    img = ee.Image(img)
    clear = img.select("cs_cdf").gte(CS_CDF_THRESHOLD)
    scaled = img.select(["B2", "B3", "B4", "B11"]).divide(10000.0).updateMask(clear)
    return ee.Image(scaled.copyProperties(img, ["system:time_start", "system:index"]))


def evaluate_scene(img):
    ndsi = img.normalizedDifference(["B3", "B11"]).rename("NDSI")
    b3 = img.select("B3")
    b4 = img.select("B4")

    valid = b3.mask()
    total = ndsi.gt(NDSI_THRESHOLD).And(b3.gt(SHADOW_B3_THRESHOLD))
    ice = total.And(b4.lte(B4_ICE_SNOW_THRESHOLD))
    snow = total.And(b4.gt(B4_ICE_SNOW_THRESHOLD))

    pixel_area = ee.Image.pixelArea()
    areas = (
        valid.multiply(pixel_area).rename("valid_m2")
        .addBands(total.multiply(pixel_area).rename("total_m2"))
        .addBands(ice.multiply(pixel_area).rename("ice_m2"))
        .addBands(snow.multiply(pixel_area).rename("snow_m2"))
    )
    stats = areas.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=glacier_geom,
        scale=20,
        maxPixels=1e9,
    )
    dt = ee.Date(img.get("system:time_start"))
    return ee.Feature(None, {
        "year": dt.get("year"),
        "date": dt.format("YYYY-MM-dd"),
        "scene_id": img.get("system:index"),
        "valid_m2": stats.get("valid_m2"),
        "total_m2": stats.get("total_m2"),
        "ice_m2": stats.get("ice_m2"),
        "snow_m2": stats.get("snow_m2"),
    })


print("Fetching scene metrics from GEE...")
fc_info = s2_linked.map(prep_scene).map(evaluate_scene).getInfo()

rows = []
for feat in fc_info["features"]:
    p = feat["properties"]
    valid_km2 = (p.get("valid_m2") or 0.0) / 1e6
    valid_frac = valid_km2 / glims_area_km2 if glims_area_km2 > 0 else 0.0
    total_km2 = (p.get("total_m2") or 0.0) / 1e6
    ice_km2 = (p.get("ice_m2") or 0.0) / 1e6
    snow_km2 = (p.get("snow_m2") or 0.0) / 1e6

    rows.append({
        "year": int(p["year"]),
        "date": p["date"],
        "scene_id": p["scene_id"],
        "valid_km2": valid_km2,
        "valid_frac": valid_frac,
        "total_raw_km2": total_km2,
        "total_norm_km2": total_km2 / valid_frac if valid_frac > 0 else 0.0,
        "ice_norm_km2": ice_km2 / valid_frac if valid_frac > 0 else 0.0,
        "snow_norm_km2": snow_km2 / valid_frac if valid_frac > 0 else 0.0,
    })

all_scenes = pd.DataFrame(rows)
all_scenes.to_csv("kebnekaise_all_scenes.csv", index=False)

valid_scenes = all_scenes[all_scenes["valid_frac"] >= MIN_VALID_FRAC].copy()

annual_records = []
for year, grp in valid_scenes.groupby("year"):
    best = grp.loc[grp["total_norm_km2"].idxmin()]
    annual_records.append({
        "year": int(year),
        "selected_date": best["date"],
        "scene_id": best["scene_id"],
        "n_valid_scenes": len(grp),
        "valid_pct": round(best["valid_frac"] * 100, 1),
        "total_norm_km2": round(best["total_norm_km2"], 2),
        "total_scene_min_km2": round(grp["total_norm_km2"].min(), 2),
        "total_scene_max_km2": round(grp["total_norm_km2"].max(), 2),
        "bare_ice_km2": round(best["ice_norm_km2"], 2),
        "fresh_snow_km2": round(best["snow_norm_km2"], 2),
    })

df = pd.DataFrame(annual_records).sort_values("year").reset_index(drop=True)
df.to_csv("kebnekaise_glacier_metrics.csv", index=False)
print("Saved kebnekaise_glacier_metrics.csv and kebnekaise_all_scenes.csv")

min_row = df.loc[df["total_norm_km2"].idxmin()]
min_year = int(min_row["year"])
base_rows = df[df["year"] == BASELINE_YEAR]
base_row = (base_rows if not base_rows.empty else df.iloc[[0]]).iloc[0]
base_year = int(base_row["year"])

if base_year != min_year:
    def load_scene_masks(scene_id):
        raw_img = ee.Image(s2_linked.filter(ee.Filter.eq("system:index", scene_id)).first())
        img = prep_scene(raw_img)
        ndsi = img.normalizedDifference(["B3", "B11"])
        b3 = img.select("B3")
        valid = b3.mask()
        snow_ice = ndsi.gt(NDSI_THRESHOLD).And(b3.gt(SHADOW_B3_THRESHOLD)).unmask(0)
        return valid, snow_ice

    valid_base, mask_base = load_scene_masks(base_row["scene_id"])
    valid_min, mask_min = load_scene_masks(min_row["scene_id"])
    mutually_valid = valid_base.And(valid_min)

    # 1: persistent, 2: loss, 3: gain
    change_img = (
        ee.Image(0)
        .where(mask_base.eq(1).And(mask_min.eq(1)), 1)
        .where(mask_base.eq(1).And(mask_min.eq(0)), 2)
        .where(mask_base.eq(0).And(mask_min.eq(1)), 3)
        .updateMask(mutually_valid)
        .clip(glacier_geom)
    )

    dem = (
        ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1")
        .filterBounds(roi_box)
        .select("DEM")
        .mosaic()
        .setDefaultProjection("EPSG:4326", None, 30)
        .clip(roi_box)
    )
    hillshade = ee.Terrain.hillshade(dem, 315, 35).visualize(min=60, max=240)
    glims_border = (
        ee.Image().byte()
        .paint(featureCollection=ee.FeatureCollection([ee.Feature(glacier_geom)]), color=1, width=1.5)
        .visualize(palette=["111111"])
    )
    change_vis = change_img.selfMask().visualize(min=1, max=3, palette=["1f78b4", "e31a1c", "00ced1"])

    composite_map = hillshade.blend(change_vis).blend(glims_border)
    url = composite_map.getThumbURL({"region": roi_box, "dimensions": 1000, "format": "png"})
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    img_arr = plt.imread(BytesIO(resp.content), format="png")
    fig, ax = plt.subplots(figsize=(7.5, 8.2))
    ax.imshow(img_arr)
    ax.axis("off")
    ax.set_title(
        f"Glacier Snow & Ice Change Inside GLIMS Outlines\n"
        f"{base_row['selected_date']} ({base_year}) vs. {min_row['selected_date']} ({min_year} Minimum)",
        fontsize=11,
        pad=10,
    )
    legend_elements = [
        Patch(facecolor="#1f78b4", label=f"Persistent Ice/Snow ({base_year} & {min_year})"),
        Patch(facecolor="#e31a1c", label=f"Loss (Present {base_year}, Absent {min_year})"),
        Patch(facecolor="#00ced1", label=f"Gain (Absent {base_year}, Present {min_year})"),
        Patch(facecolor="none", edgecolor="#111111", linewidth=1.5, label="GLIMS Glacier Boundary"),
    ]
    ax.legend(
        handles=legend_elements,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=2,
        frameon=True,
        fontsize=8.5,
    )
    plt.tight_layout()
    plt.savefig("kebnekaise_change_map.png", dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved kebnekaise_change_map.png ({base_year} vs {min_year})")
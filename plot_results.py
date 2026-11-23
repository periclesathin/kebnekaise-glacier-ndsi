import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("kebnekaise_glacier_metrics.csv")

fig, (ax1, ax2) = plt.subplots(
    2, 1, figsize=(9.5, 7.5), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]}
)

ax1.fill_between(
    df["year"],
    df["total_scene_min_km2"],
    df["total_scene_max_km2"],
    color="#1f77b4",
    alpha=0.15,
    label="Late-Summer Scene Spread (Min–Max)",
)
ax1.plot(df["year"], df["total_norm_km2"], marker="o", linewidth=2, color="#1f77b4", label="End-of-Ablation Total (NDSI > 0.40)")
ax1.plot(df["year"], df["bare_ice_km2"], marker="s", linewidth=2, color="#d62728", label="Exposed Bare Glacier Ice (B4 ≤ 0.45)")
ax1.plot(df["year"], df["fresh_snow_km2"], marker="^", linestyle="--", linewidth=1.8, color="#17becf", label="Residual Snow / Firn (B4 > 0.45)")
ax1.set_title("Kebnekaise Massif – Glacier Surface State Inside GLIMS Boundaries (2018–2026)")
ax1.set_ylabel("Normalized Area [km²]")
ax1.grid(True, linestyle="--", alpha=0.5)
ax1.legend(loc="upper right", frameon=True, fontsize=8.5)

bars = ax2.bar(df["year"], df["valid_pct"], color="#2ca02c", alpha=0.75, width=0.55, label="Cloud-Free Glacier Coverage [%]")
ax2.axhline(80, color="#555555", linestyle=":", linewidth=1.2, label="80% Quality Threshold")
ax2.set_ylim(0, 112)
ax2.set_ylabel("Valid Pixels [%]")
ax2.set_xlabel("Year (Aug 1 – Sep 15 Sentinel-2 scenes, Cloud Score+ cs_cdf ≥ 0.60)")
ax2.grid(True, axis="y", linestyle="--", alpha=0.5)

for bar, n_sc in zip(bars, df["n_valid_scenes"]):
    ax2.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 2,
        f"n={n_sc}",
        ha="center",
        va="bottom",
        fontsize=8,
    )

plt.tight_layout()
plt.savefig("glacier_analysis_summary.png", dpi=200)
plt.close()

cols = ["year", "selected_date", "n_valid_scenes", "valid_pct", "total_norm_km2", "bare_ice_km2", "fresh_snow_km2"]
print(df[cols].to_markdown(index=False))
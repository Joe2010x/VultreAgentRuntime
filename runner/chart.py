import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot


def main():
    sales_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("sample-sales.csv")
    monthly_sales = defaultdict(int)
    with sales_file.open(newline="", encoding="utf-8") as source:
        rows = csv.DictReader(source)
        required = {"month", "product", "revenue_usd"}
        if not required.issubset(rows.fieldnames or []):
            raise ValueError("CSV must contain month, product, and revenue_usd columns.")
        for row in rows:
            month, product = row["month"], row["product"]
            if not month or not product:
                raise ValueError(f"Missing month or product on CSV line {rows.line_num}.")
            monthly_sales[month, product] += int(row["revenue_usd"])
    if not monthly_sales:
        raise ValueError("CSV must contain at least one sales record.")

    months = sorted({month for month, _ in monthly_sales})
    winners = [
        max(
            (revenue, product)
            for (sales_month, product), revenue in monthly_sales.items()
            if sales_month == month
        )
        for month in months
    ]

    figure, axes = pyplot.subplots(figsize=(8, 4.5), layout="constrained")
    bars = axes.bar(months, [revenue for revenue, _ in winners], color="#176B73")
    axes.bar_label(
        bars,
        labels=[f"{product}\n${revenue:,}" for revenue, product in winners],
        padding=4,
    )
    axes.margins(y=0.2)
    axes.set(title="Top product by month", ylabel="Revenue (USD)")
    figure.savefig(sys.stdout.buffer, format="png", dpi=140)
    pyplot.close(figure)


if __name__ == "__main__":
    main()

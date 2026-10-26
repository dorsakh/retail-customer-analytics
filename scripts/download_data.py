from pathlib import Path

import kagglehub


DATASET = "frtgnn/dunnhumby-the-complete-journey"
DATA_DIR = Path("data/raw/complete_journey")

FILES = (
    "transaction_data.csv",
    "product.csv",
    "hh_demographic.csv",
    "campaign_desc.csv",
    "campaign_table.csv",
    "coupon.csv",
    "coupon_redempt.csv",
)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for filename in FILES:
        file_path = DATA_DIR / filename

        if not file_path.is_file():
            print(f"Downloading {filename}...")

            kagglehub.dataset_download(
                DATASET,
                path=filename,
                output_dir=str(DATA_DIR),
            )

        if not file_path.is_file():
            raise FileNotFoundError(
                f"Required dataset file is missing: {file_path}"
            )

        size_mb = file_path.stat().st_size / (1024**2)

        print(f"{filename}: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
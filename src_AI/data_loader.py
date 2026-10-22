
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent

FILES = {
    "jobs": BASE_DIR / "input" / "jobs_output_hiring-cafe.csv",
    "competencies": BASE_DIR / "data" / "competency_dictionary.csv",
    "crl_scale": BASE_DIR / "data" / "crl_scale.csv",
    "role_mapping": BASE_DIR / "data" / "role_competency_mapping.csv",
    "crl_descriptions": BASE_DIR / "data" / "role_crl_descriptions.csv",
}


def read_csv_safely(path):
    """Read a CSV using common encodings."""

    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue

    # Last resort: replace invalid characters
    return pd.read_csv(
        path,
        encoding="utf-8",
        encoding_errors="replace",
        on_bad_lines="warn",
    )


def load_all_data():
    """Load all job-posting and CRL datasets."""

    data = {}

    for name, path in FILES.items():
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            df = read_csv_safely(path)
            data[name] = df

            print(f"Loaded {name}: {len(df)} rows")
            print(f"Columns: {df.columns.tolist()}")

        except Exception as error:
            raise RuntimeError(
                f"Failed to load {name} from {path}: {error}"
            ) from error

    return data


if __name__ == "__main__":
    datasets = load_all_data()
    print("\nAll datasets loaded successfully.")

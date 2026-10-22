"""Build or refresh the project's CRL Chroma index from its data CSVs."""

from src_AI.rag_retriever import get_vector_store


def main():
    _, collection = get_vector_store()
    print(
        f"CRL Chroma index ready: {collection.count()} records "
        f"in collection '{collection.name}'.",
        flush=True,
    )


if __name__ == "__main__":
    main()

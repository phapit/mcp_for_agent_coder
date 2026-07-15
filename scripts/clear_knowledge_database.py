#!/usr/bin/env python3
"""Drop the configured MongoDB database used by knowledge_service."""

import argparse
import os
import sys

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete all data from the knowledge_service MongoDB database."
    )
    parser.add_argument(
        "--mongodb-uri",
        default=os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
        help="MongoDB connection URI. Uses MONGODB_URI or localhost by default.",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("MONGODB_DB_NAME", "knowledge_service"),
        help="Database to drop. Uses MONGODB_DB_NAME or knowledge_service by default.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List collections and document counts without deleting anything.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the destructive database deletion.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if not args.database.strip():
        print("Database name must not be empty.", file=sys.stderr)
        return 2
    if not args.dry_run and not args.yes:
        print(
            "Refusing to delete data without --yes. Use --dry-run to inspect first.",
            file=sys.stderr,
        )
        return 2

    try:
        from pymongo import MongoClient
        from pymongo.errors import PyMongoError
    except ImportError:
        print(
            "Missing dependency: pymongo. Install it or run the script in the service container.",
            file=sys.stderr,
        )
        return 1

    client = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)
    try:
        database = client[args.database]
        collections = database.list_collection_names()
        print(f"Database: {args.database}")
        print(f"Collections: {len(collections)}")
        for name in collections:
            print(f"- {name}: {database[name].count_documents({})} documents")

        if args.dry_run:
            print("Dry run: no data was deleted.")
            return 0

        client.drop_database(args.database)
        print(f"Deleted database: {args.database}")
        return 0
    except PyMongoError as exc:
        print(f"Failed to clear MongoDB database: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

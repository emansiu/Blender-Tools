"""Package assets/HDRI_COLLECTION for the GitHub release Download HDRIs reads.

Plain Python (no Blender). Run it on the machine that has the HDRIs:

    python scripts/package_hdris.py

It writes one zip per category plus hdri_manifest.json into dist/hdris/. Each
zip holds <Category>/hdri_versions/*.hdr|.exr and the category's thumbnails --
the layout render_tools.scan_hdris() expects. Then publish them:

    gh release create hdris-v1 dist/hdris/* --title "HDRI Collection v1"

The tag must match HDRI_RELEASE_URL in src/Emanate_Tools/tools/render_tools.py.
GitHub caps release assets at 2 GB per file, so a category over that is an error.
"""

import hashlib
import json
import os
import sys
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION_DIR = os.path.join(REPO_ROOT, "assets", "HDRI_COLLECTION")
OUTPUT_DIR = os.path.join(REPO_ROOT, "dist", "hdris")
MANIFEST_NAME = "hdri_manifest.json"

HDRI_VERSIONS_DIRNAME = "hdri_versions"
HDRI_EXTENSIONS = (".hdr", ".exr")
THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".png")
MAX_ASSET_BYTES = 2 * 1024**3


def category_files(category_dir):
    """(path on disk, path inside the category) for every file a category ships."""
    files = []
    for name in sorted(os.listdir(category_dir)):
        path = os.path.join(category_dir, name)
        if os.path.isfile(path) and name.lower().endswith(THUMBNAIL_EXTENSIONS):
            files.append((path, name))
    versions_dir = os.path.join(category_dir, HDRI_VERSIONS_DIRNAME)
    if os.path.isdir(versions_dir):
        for name in sorted(os.listdir(versions_dir)):
            if name.lower().endswith(HDRI_EXTENSIONS):
                files.append((os.path.join(versions_dir, name), f"{HDRI_VERSIONS_DIRNAME}/{name}"))
    return files


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    if not os.path.isdir(COLLECTION_DIR):
        sys.exit(f"No HDRI collection at {COLLECTION_DIR}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    manifest = []
    for category in sorted(os.listdir(COLLECTION_DIR)):
        category_dir = os.path.join(COLLECTION_DIR, category)
        if not os.path.isdir(category_dir):
            continue
        files = category_files(category_dir)
        if not any(inner.startswith(HDRI_VERSIONS_DIRNAME) for _, inner in files):
            print(f"skip {category}: no {HDRI_VERSIONS_DIRNAME}/ HDRIs")
            continue

        zip_name = f"{category.replace(' ', '_')}.zip"
        zip_path = os.path.join(OUTPUT_DIR, zip_name)
        # .hdr is already RLE-compressed and barely shrinks; STORED keeps this fast.
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as archive:
            for path, inner in files:
                archive.write(path, f"{category}/{inner}")

        size = os.path.getsize(zip_path)
        if size > MAX_ASSET_BYTES:
            sys.exit(f"{zip_name} is {size / 2**30:.2f} GB, over GitHub's 2 GB asset limit -- split the category")
        manifest.append({"category": category, "file": zip_name, "size": size, "sha256": sha256_of(zip_path)})
        print(f"{zip_name}: {len(files)} files, {size / 2**20:.0f} MB")

    with open(os.path.join(OUTPUT_DIR, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    total = sum(entry["size"] for entry in manifest)
    print(f"\n{len(manifest)} categories, {total / 2**30:.2f} GB -> {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

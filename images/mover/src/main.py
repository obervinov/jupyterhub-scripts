"""
JupyterHub Image Mover Script

This script provides automated image organization functionality for Nextcloud storage
systems. It automatically moves images from an unsorted directory to organized locations
based on their assigned tags.
THIS SCRIPT REQUIRES "PYTHON API" EXTENSION TO BE INSTALLED IN NEXTCLOUD INSTANCE https://github.com/cloud-py-api/nc_py_api

Main Features:
- Automated scanning of Nextcloud directories for tagged images
- Tag-based file organization and movement
- Secure credential management using Vault KV store
- Automatic tag removal after successful file processing
- Integration with Nextcloud API for advanced file operations

Workflow:
1. Scans the UNSORTED_REMOTE_DIR for images with assigned tags
2. Extracts tags from each image file
3. Moves images to organized directories based on tag names
4. Removes processed tags from files after successful movement
5. Provides detailed logging of all operations

Configuration:
- Nextcloud credentials: Stored in Vault KV store under 'webdav' secret
  Format: {"host_url": "https://...", "username": "...", "password": "..."}
- Constants: Configurable via Vault 'mover_constants' secret
  Format: {
    "IMAGES_ROOT_DIR": "data",
    "PARENT_TAG_VALUE": "ai",
    "UNSORTED_REMOTE_DIR": "_unsorted"
  }
  - IMAGES_ROOT_DIR: Base directory for organized images
  - PARENT_TAG_VALUE: Marker for relevant tags to process
  - UNSORTED_REMOTE_DIR: Source directory containing unorganized images
- Thread limit: Maximum concurrent processing threads (currently set to 3)

Load on Nextcloud:
- Images are discovered per tag with one REPORT request (systemtag filter) instead of
  fetching tags for every file in UNSORTED_REMOTE_DIR, so untagged files cost nothing
- Files are moved with a raw WebDAV MOVE: nc_py_api's files.move() follows every MOVE
  with a SEARCH by fileid over the whole user home, which is what overloaded the instance

Documentation:
- https://cloud-py-api.github.io/nc_py_api/_modules/nc_py_api/files/files.html#FilesAPI.move
- https://cloud-py-api.github.io/nc_py_api/reference/Files/Files.html
"""
import argparse
import logging
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib.parse import quote


LOGGER = logging.getLogger(__name__)


nextcloud_client = None
IMAGES_ROOT_DIR = ""
UNSORTED_REMOTE_DIR = ""
PARENT_TAG_VALUE = ""
THREADS_LIMIT = 3


def configure_nextcloud() -> None:
    """
    Initialize Nextcloud client and configuration values from Vault.
    """
    global nextcloud_client, IMAGES_ROOT_DIR, UNSORTED_REMOTE_DIR, PARENT_TAG_VALUE

    from vault import VaultClient
    from nc_py_api import Nextcloud

    vault = VaultClient()
    webdav_secret = vault.kv2engine.read_secret("webdav")
    constants_secret = vault.kv2engine.read_secret("mover_constants")

    nextcloud_client = Nextcloud(
        nextcloud_url=webdav_secret['host_url'],
        nc_auth_user=webdav_secret['username'],
        nc_auth_pass=webdav_secret['password']
    )
    IMAGES_ROOT_DIR = constants_secret['IMAGES_ROOT_DIR']
    UNSORTED_REMOTE_DIR = f"{IMAGES_ROOT_DIR}/{constants_secret['UNSORTED_REMOTE_DIR']}"
    PARENT_TAG_VALUE = constants_secret['PARENT_TAG_VALUE']


def get_parent_tags() -> list:
    """
    Retrieve the tags relevant for processing from the Nextcloud instance.

    Only tags with the 'PARENT_TAG_VALUE:' prefix are returned (ex. ai:cats).

    Returns:
        list: A list of tag objects. Each tag object contains metadata like tag_id,
              display_name, and other properties.
    """
    return [
        tag for tag in nextcloud_client.files.list_tags()
        if tag.display_name.startswith(f"{PARENT_TAG_VALUE}:")
    ]


def get_tagged_images(tags: list) -> list:
    """
    Retrieve images with the given tags that are located directly in UNSORTED_REMOTE_DIR.

    Each tag costs a single REPORT request, regardless of how many files are in the
    unsorted directory. A file with several relevant tags is returned once, with the
    first of them.

    Args:
        tags (list): A list of tag objects to search files by.

    Returns:
        list: A list of (node, tag) tuples, where node is a Nextcloud file node object
              and tag is the tag that determines its target directory.
    """
    images = {}
    unsorted_dir = UNSORTED_REMOTE_DIR.strip('/')
    for tag in tags:
        for node in nextcloud_client.files.list_by_criteria(tags=[tag]):
            if node.is_dir or node.user_path.strip('/').rsplit('/', 1)[0] != unsorted_dir:
                continue
            images.setdefault(node.info.fileid, (node, tag))
    return list(images.values())


def dav_move(path_src: str, path_dest: str) -> None:
    """
    Move a file with a single WebDAV MOVE request.

    nc_py_api's files.move() runs a SEARCH by fileid over the whole user home after
    every MOVE to return the new node. The result is not needed here, and those
    searches are the heaviest part of the load on Nextcloud.

    Args:
        path_src (str): Path of the existing file relative to the user's root directory.
        path_dest (str): Target path relative to the user's root directory.
    """
    from nc_py_api._exceptions import check_error
    from nc_py_api.files._files import dav_get_obj_path
    from niquests.structures import CaseInsensitiveDict

    session = nextcloud_client.files._session
    dest = session.cfg.dav_endpoint + quote(dav_get_obj_path(session.user, path_dest))
    response = session.adapter_dav.request(
        "MOVE",
        quote(dav_get_obj_path(session.user, path_src)),
        headers=CaseInsensitiveDict({"Destination": dest.encode("utf-8"), "Overwrite": "F"}),
    )
    check_error(response, f"move: user={session.user}, src={path_src}, dest={dest}")


def move_image(node: object, tag: object, debug: bool = False) -> None:
    """
    Move an image file to an organized directory based on its tag.

    This function processes a single image file by:
    1. Creating a target path based on the tag name (removing 'PARENT_TAG_VALUE' prefix)
    2. Moving the file to the organized directory structure
    3. Removing the processed tag from the file

    The function assumes tags follow the format 'PARENT_TAG_VALUE:category' where 'category'
    becomes the subdirectory name under IMAGES_ROOT_DIR (ex. ai:cats -> IMAGES_ROOT_DIR/cats).
    PARENT_TAG_VALUE is marker for relevant tags to process. It can be everything you want.

    Args:
        node (object): A Nextcloud file node object containing file metadata
                      including name, path, and file ID. This represents the
                      image file to be moved.
        tag (object): The tag object that determines the target directory.

    Returns:
        None: This function performs file operations but returns nothing.
    """
    tag_name = tag.display_name
    target_path = f"{IMAGES_ROOT_DIR}/{tag_name.replace(PARENT_TAG_VALUE + ':', '')}/{node.user_path.split('/')[-1]}"
    if debug:
        LOGGER.debug("Moving %s to %s", node.name, target_path)
    # Move file
    dav_move(path_src=node.user_path, path_dest=target_path)
    # Remove tag from processed file (fileid does not change on move)
    nextcloud_client.files.unassign_tag(file_id=node.info.fileid, tag_id=tag.tag_id)
    if debug:
        LOGGER.debug("Processed %s and unassigned tag %s", node.name, tag_name)


def process_image(node: object, tag: object, debug: bool = False) -> None:
    """
    Move a single image to the directory of its tag.

    This function is intended to be called concurrently via ThreadPoolExecutor.

    Args:
        node (object): A Nextcloud file node object representing the image to process.
        tag (object): The tag object that determines the target directory.
    """
    try:
        move_image(node=node, tag=tag, debug=debug)
    except Exception as exc:
        raise RuntimeError(f"Failed processing file '{node.name}'") from exc


def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments for the image mover script.
    """
    parser = argparse.ArgumentParser(
        description="Move tagged images from the unsorted directory into tag-based folders."
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output, including the full tag list and per-file operations.",
    )
    return parser.parse_args()


def configure_logging(debug: bool) -> None:
    """
    Configure logging output for the script.
    """
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.ERROR,
        format="%(levelname)s: %(message)s",
    )


def print_progress(completed: int, total: int, width: int = 40) -> None:
    """
    Render a compact progress bar for processed files.
    """
    if total == 0:
        return

    filled = int(width * completed / total)
    bar = "#" * filled + "-" * (width - filled)
    print(f"\rProgress: [{bar}] {completed}/{total}", end="", flush=True)


if __name__ == "__main__":
    args = parse_args()
    configure_logging(debug=args.debug)
    configure_nextcloud()

    # Get relevant tags and the images in the unsorted directory that carry them
    tags = get_parent_tags()
    if args.debug:
        LOGGER.debug("Tags list: %s", tags)

    images = get_tagged_images(tags=tags)
    total_images = len(images)
    print(f"Tagged files found: {total_images}")

    if total_images == 0:
        print("Done.")
        sys.exit(0)

    # Process images concurrently: move each file and unassign its tag in parallel
    print(f"Processing images with up to {THREADS_LIMIT} parallel threads...")
    completed = 0
    image_iterator = iter(images)
    with ThreadPoolExecutor(max_workers=THREADS_LIMIT) as executor:
        futures = {
            executor.submit(process_image, node, tag, args.debug)
            for node, tag in [next(image_iterator) for _ in range(min(THREADS_LIMIT, total_images))]
        }
        while futures:
            done, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                completed += 1
                print_progress(completed=completed, total=total_images)

                try:
                    future.result()
                except Exception:
                    LOGGER.exception("Image processing failed")

                try:
                    next_node, next_tag = next(image_iterator)
                except StopIteration:
                    continue

                futures.add(executor.submit(process_image, next_node, next_tag, args.debug))

    print()
    print("Done.")
    sys.exit(0)

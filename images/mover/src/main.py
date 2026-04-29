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
- Thread limit: Maximum concurrent processing threads (currently set to 10)

Documentation:
- https://cloud-py-api.github.io/nc_py_api/_modules/nc_py_api/files/files.html#FilesAPI.move
- https://cloud-py-api.github.io/nc_py_api/reference/Files/Files.html
"""
import argparse
import logging
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait


LOGGER = logging.getLogger(__name__)


nextcloud_client = None
IMAGES_ROOT_DIR = ""
UNSORTED_REMOTE_DIR = ""
PARENT_TAG_VALUE = ""
THREADS_LIMIT = 10


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


def get_images_list() -> list:
    """
    Retrieve list of images to process from the unsorted WebDAV/Nextcloud folder.

    This function scans the UNSORTED_REMOTE_DIR directory and returns a list of
    file nodes that need to be processed for tag-based organization.

    Returns:
        list: A list of file node objects representing images in the unsorted directory.
              Each node contains file metadata including name, path, and file ID.
    """
    return nextcloud_client.files.listdir(UNSORTED_REMOTE_DIR)


def get_image_tags(file_id: str) -> list:
    """
    Get tags of image

    Args:
        file_id (int): nc file id
    """
    return nextcloud_client.files.get_tags(file_id=file_id)


def get_tags_list() -> list:
    """
    Retrieve all available tags from the Nextcloud instance.

    This function fetches the complete list of tags that exist in the
    Nextcloud system, which can be useful for debugging and understanding
    the available tag structure.

    Returns:
        list: A list of all tag objects available in the Nextcloud instance.
              Each tag object contains metadata like tag_id, display_name,
              and other properties.
    """
    return nextcloud_client.files.list_tags()


def move_image(node: object, tags: list, debug: bool = False) -> None:
    """
    Move an image file to an organized directory based on its tags.

    This function processes a single image file by:
    1. Extracting the first tag's information
    2. Creating a target path based on the tag name (removing 'PARENT_TAG_VALUE' prefix)
    3. Moving the file to the organized directory structure
    4. Removing the processed tag from the file

    The function assumes tags follow the format 'PARENT_TAG_VALUE:category' where 'category'
    becomes the subdirectory name under IMAGES_ROOT_DIR (ex. ai:cats -> IMAGES_ROOT_DIR/cats).
    PARENT_TAG_VALUE is marker for relevant tags to process. It can be everything you want.

    Args:
        node (object): A Nextcloud file node object containing file metadata
                      including name, path, and file ID. This represents the
                      image file to be moved.
        tags (list): A list of tag objects associated with the file. Only the
                    first tag in the list will be processed for determining
                    the target directory.

    Returns:
        None: This function performs file operations but returns nothing.

    Note:
        - Only the first tag is processed; additional tags are ignored
        - Tag names are expected to have 'PARENT_TAG_VALUE:' prefix which gets removed
        - Files are moved to: IMAGES_ROOT_DIR/{tag_name_without_prefix}/filename
    """
    tag_id = tags[0].tag_id
    tag_name = tags[0].display_name
    target_path = f"{IMAGES_ROOT_DIR}/{tag_name.replace(PARENT_TAG_VALUE + ':', '')}/{node.user_path.split('/')[-1]}"
    if debug:
        LOGGER.debug("Moving %s to %s", node.name, target_path)
    # Move file
    nextcloud_client.files.move(path_src=node, path_dest=target_path)
    # Remove tag from processed file
    nextcloud_client.files.unassign_tag(file_id=node, tag_id=tag_id)
    if debug:
        LOGGER.debug("Processed %s and unassigned tag %s", node.name, tag_name)


def process_image(node: object, debug: bool = False) -> None:
    """
    Retrieve tags for a single image and move it if tags are present.

    This function is intended to be called concurrently via ThreadPoolExecutor.

    Args:
        node (object): A Nextcloud file node object representing the image to process.
    """
    try:
        tags = get_image_tags(file_id=node)
        if len(tags) > 0:
            move_image(node=node, tags=tags, debug=debug)
        elif debug:
            LOGGER.debug("Skipping %s because it has no tags", node.name)
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

    # Get files list in specific directory
    nodes = get_images_list()
    total_nodes = len(nodes)
    print(f"Files found: {total_nodes}")

    if total_nodes == 0:
        print("Done.")
        sys.exit(0)

    if args.debug:
        all_tags = get_tags_list()
        LOGGER.debug("Tags list: %s", all_tags)

    # Process images concurrently: fetch tags + move each file in parallel
    print(f"Processing images with up to {THREADS_LIMIT} parallel threads...")
    completed = 0
    node_iterator = iter(nodes)
    with ThreadPoolExecutor(max_workers=THREADS_LIMIT) as executor:
        futures = {
            executor.submit(process_image, node, args.debug)
            for node in [next(node_iterator) for _ in range(min(THREADS_LIMIT, total_nodes))]
        }
        while futures:
            done, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                completed += 1
                print_progress(completed=completed, total=total_nodes)

                try:
                    future.result()
                except Exception:
                    LOGGER.exception("Image processing failed")

                try:
                    next_node = next(node_iterator)
                except StopIteration:
                    continue

                futures.add(executor.submit(process_image, next_node, args.debug))

    print()
    print("Done.")
    sys.exit(0)

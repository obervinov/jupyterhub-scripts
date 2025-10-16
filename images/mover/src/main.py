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
- Constants: Configurable via Vault 'mover_constants' secret
  - IMAGES_ROOT_DIR: Base directory for organized images
  - UNSORTED_REMOTE_DIR: Source directory containing unorganized images
- Thread limit: Maximum concurrent processing threads (currently set to 10)

Documentation:
- https://cloud-py-api.github.io/nc_py_api/_modules/nc_py_api/files/files.html#FilesAPI.move
- https://cloud-py-api.github.io/nc_py_api/reference/Files/Files.html
"""
import sys
from vault import VaultClient
from nc_py_api import Nextcloud


# Secrets and credentials
vault = VaultClient()
webdav_secret = vault.kv2engine.read_secret("webdav")
constants_secret = vault.kv2engine.read_secret("mover_constants")

# Nextcloud client
nextcloud_client = Nextcloud(
    nextcloud_url=webdav_secret['host_url'],
    nc_auth_user=webdav_secret['username'],
    nc_auth_pass=webdav_secret['password']
)


# Constants
IMAGES_ROOT_DIR = constants_secret['IMAGES_ROOT_DIR']
UNSORTED_REMOTE_DIR = constants_secret['UNSORTED_REMOTE_DIR']
PARENT_TAG_VALUE = constants_secret['PARENT_TAG_VALUE']
THREADS_LIMIT = 10


def get_images_list() -> list:
    """
    Retrieve list of images to process from the unsorted WebDAV/Nextcloud folder.

    This function scans the UNSORTED_REMOTE_DIR directory and returns a list of
    file nodes that need to be processed for tag-based organization.

    Returns:
        list: A list of file node objects representing images in the unsorted directory.
              Each node contains file metadata including name, path, and file ID.
    """
    print("Retrieving objects list...")
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


def move_image(node: object, tags: list) -> None:
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
    print(f"File {node.name} will be to move in the {target_path}")
    # Move file
    nextcloud_client.files.move(path_src=node, path_dest=target_path)
    # Remove tag from processed file
    nextcloud_client.files.unassign_tag(file_id=node, tag_id=tag_id)
    print(f"File {node.name} has been processed. Tag has been unassigned.")


if __name__ == "__main__":
    # Get files list in specific directory
    nodes = get_images_list()
    print(f"Files found: {len(nodes)}")

    # Extract all tags in instance
    all_tags = get_tags_list()
    print(f"Tags list:{all_tags}")

    # Find tag per image
    print("Extracting tags per image...")
    for node in nodes:
        tags = get_image_tags(file_id=node)
        if len(tags) > 0:
            move_image(node=node, tags=tags)
    print("Done.")
    sys.exit(0)

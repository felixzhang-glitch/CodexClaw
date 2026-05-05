from channel.feishu.media import extract_local_image_paths, find_recent_generated_images, remove_local_image_references


def test_extract_local_image_paths_from_file_uri(tmp_path) -> None:
    image_path = tmp_path / "generated_image.png"
    image_path.write_bytes(b"fake")
    text = f"Generated Image:\nSaved to: file://{image_path}"

    assert extract_local_image_paths(text) == [str(image_path)]
    assert "file://" not in remove_local_image_references(text)


def test_find_recent_generated_images(tmp_path) -> None:
    image_path = tmp_path / "nested" / "image.png"
    image_path.parent.mkdir()
    image_path.write_bytes(b"fake")

    assert find_recent_generated_images(str(tmp_path), since=image_path.stat().st_mtime - 1) == [str(image_path)]

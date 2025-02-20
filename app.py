import streamlit as st
import re
from pytube import YouTube
import io
from urllib.parse import urlparse, parse_qs
import xml.etree.ElementTree as ET
import requests
import json
import zipfile
import math
import time


def extract_video_id(url):
    """Extract YouTube video ID from various URL formats."""
    if not url:
        return None

    url = url.strip()
    parsed_url = urlparse(url)

    if 'youtu.be' in parsed_url.netloc:
        path = parsed_url.path.lstrip('/')
        video_id = path.split('?')[0]
        video_id = video_id.split('/')[0]
        return video_id

    elif 'youtube.com' in parsed_url.netloc:
        if '/watch' in parsed_url.path:
            query_params = parse_qs(parsed_url.query)
            return query_params.get('v', [None])[0]
        elif '/embed/' in parsed_url.path or '/v/' in parsed_url.path or '/live/' in parsed_url.path:
            path_parts = parsed_url.path.split('/')
            for part in reversed(path_parts):
                if part:
                    return part
        elif 'shorts' in parsed_url.path:
            path_parts = parsed_url.path.split('/')
            return path_parts[-1]
    return None


def get_captions_from_pytube(video_id):
    """Try to get captions using PyTube."""
    try:
        yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
        captions = yt.captions

        if not captions or len(captions.all()) == 0:
            return False, "No captions available for this video"

        caption_track = None
        for track in captions.all():
            if track.code.startswith(('en', 'a.en')):
                caption_track = track
                break

        if caption_track is None and captions.all():
            caption_track = captions.all()[0]

        if caption_track:
            transcript = caption_track.generate_srt_captions()
            clean_text = re.sub(r'\d+\s+\d+:\d+:\d+,\d+ --> \d+:\d+:\d+,\d+\s+', '', transcript)
            clean_text = re.sub(r'\n\n', ' ', clean_text)
            return True, clean_text
        else:
            return False, "No suitable captions found"

    except Exception as e:
        return False, f"Error with PyTube: {str(e)}"


def get_captions_from_api(video_id):
    """Try to get captions using direct API access, with retries and headers."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    })

    max_retries = 3
    retry_delay = 1

    for attempt in range(max_retries):
        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            response = session.get(video_url)

            if response.status_code != 200:
                return False, f"Failed to access video page (status code: {response.status_code})"

            caption_params = {'v': video_id, 'lang': 'en'}
            caption_url = "https://www.youtube.com/api/timedtext"
            caption_response = session.get(caption_url, params=caption_params)

            if caption_response.status_code == 200 and caption_response.text:
                try:
                    root = ET.fromstring(caption_response.text)
                    transcript_text = " ".join([elem.text for elem in root.findall(".//text") if elem.text])
                    if transcript_text:
                        return True, transcript_text
                except Exception:
                    pass

            data_pattern = r'(?:"captionTracks":(\[.*?\])|"playerCaptionsTracklistRenderer":.*?(\[.*?\]))'
            matches = re.findall(data_pattern, response.text)
            caption_data = None

            for match_group in matches:
                for match in match_group:
                    if match:
                        try:
                            caption_data = json.loads(match)
                            break
                        except (json.JSONDecodeError, TypeError):
                            continue
                if caption_data:
                    break

            if not caption_data:
                return False, "No caption data found in video page"

            for track in caption_data:
                if "baseUrl" in track:
                    caption_url = track["baseUrl"]
                    caption_response = session.get(caption_url)
                    if caption_response.status_code == 200:
                        try:
                            root = ET.fromstring(caption_response.text)
                            transcript_text = " ".join([elem.text for elem in root.findall(".//text") if elem.text is not None])
                            if transcript_text:
                                return True, transcript_text
                        except ET.ParseError as xml_err:
                            return False, f"Failed to parse caption XML: {xml_err}"
            return False, "No suitable caption URL found"

        except requests.RequestException as e:
            error_msg = f"Network error: {e}"
            if attempt < max_retries - 1:
                st.warning(f"Attempt {attempt + 1} failed: {error_msg}. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                return False, error_msg
        except Exception as e:
            return False, f"An unexpected error occurred: {e}"

    return False, "Max retries exceeded"


def sanitize_filename(name):
    """Create a safe filename from any input string."""
    if not name:
        return "transcript"
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.replace(" ", "_")
    name = name[:100]
    return name if name else "transcript"


def main():
    st.set_page_config(page_title="Tony the YouTube Transcript Extractor", page_icon="📝")

    st.title("YouTube Transcript Extractor")
    st.markdown("""
    Extract transcripts from YouTube videos. Enter one or more YouTube URLs below.
    """)

    url_input = st.text_area(
        "YouTube Video URLs (one per line):",
        placeholder="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://youtu.be/anothervideoID"
    )

    name_input = st.text_area(
        "Custom Filenames (optional, one per line):",
        placeholder="video_one\nvideo_two"
    )

    with st.expander("Advanced Options"):
        extraction_method = st.radio(
            "Extraction Method",
            ["Auto (try all methods)", "PyTube", "Direct API Access"],
            index=0
        )

    success_count = 0
    fail_count = 0

    if st.button("Extract Transcripts"):
        if not url_input.strip():
            st.warning("Please enter at least one YouTube URL.")
            return

        urls = []
        for url in url_input.strip().split('\n'):
            url = url.strip()
            if url and url not in urls:
                urls.append(url)
        names = [name.strip() for name in name_input.strip().split('\n') if name.strip()]

        st.info(f"Processing {len(urls)} video(s)...")

        if 'results' not in st.session_state:
            st.session_state.results = []
        else:
            st.session_state.results = []

        for i, url in enumerate(urls):
            custom_name = names[i] if i < len(names) else f"video_{i+1}"
            sanitized_name = sanitize_filename(custom_name)
            filename = f"{sanitized_name}.txt"

            video_id = extract_video_id(url)
            if not video_id:
                st.error(f"❌ Could not extract video ID from URL: {url}")
                fail_count += 1
                continue

            st.markdown(f"### Processing: {url}")
            st.write(f"Video ID: {video_id}")

            success = False
            transcript = ""
            error_msg = ""

            if extraction_method in ["Auto (try all methods)", "PyTube"]:
                st.write("Trying PyTube extraction...")
                success, result = get_captions_from_pytube(video_id)
                if success:
                    transcript = result
                else:
                    error_msg = result
                    if extraction_method == "PyTube":
                        st.error(f"❌ PyTube extraction failed: {error_msg}")

            if not success and extraction_method in ["Auto (try all methods)", "Direct API Access"]:
                st.write("Trying Direct API extraction...")
                success, result = get_captions_from_api(video_id)
                if success:
                    transcript = result
                else:
                    error_msg = result
                    if extraction_method == "Direct API Access" or extraction_method == "Auto (try all methods)":
                        st.error(f"❌ API extraction failed: {error_msg}")

            if success:
                try:
                    success_count += 1
                    st.success(f"✅ Successfully extracted transcript for {url}")
                    st.session_state.results.append((filename, transcript, video_id))

                    with st.expander("Preview Transcript"):
                        st.code(transcript[:1000] + ("..." if len(transcript) > 1000 else ""))

                    st.download_button(
                        label=f"Download {filename}",
                        data=transcript,
                        file_name=filename,
                        mime="text/plain",
                        key=f"download_{video_id}_{i}"
                    )
                except Exception as e:
                    fail_count += 1
                    st.error(f"❌ Unexpected error processing {url}: {e}")
                    st.write("Please check the URL and try again.")
            else:
                fail_count += 1
                st.error(f"❌ Failed to extract transcript for {url}")
                st.write(f"Reason: {error_msg}")

            st.markdown("---")

        st.markdown(f"## Summary: {success_count} succeeded, {fail_count} failed")

    if st.session_state.get('results'):
        chunk_size = 25
        num_chunks = math.ceil(len(st.session_state.results) / chunk_size)

        for i in range(num_chunks):
            start_index = i * chunk_size
            end_index = min((i + 1) * chunk_size, len(st.session_state.results))
            chunk = st.session_state.results[start_index:end_index]

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file_name, content, _ in chunk:
                    zip_file.writestr(file_name, content)
            zip_buffer.seek(0)

            st.download_button(
                label=f"Download Transcripts (Part {i + 1} of {num_chunks})",
                data=zip_buffer,
                file_name=f"youtube_transcripts_part_{i + 1}.zip",
                mime="application/zip",
                key=f"download_all_part_{i}"
            )

    if fail_count > 0:
        st.markdown("""
        ## Troubleshooting

        If transcripts are failing to extract, consider:

        1.  **Privacy Restrictions**: Some videos have disabled captions/transcripts.
        2.  **Regional Restrictions**: Some videos may not be available with captions in your region.
        3.  **Authentication**:  Your browser might have access that Streamlit Cloud doesn't.

        Try running the app locally if you suspect these issues.
        """)


if __name__ == '__main__':
    main()

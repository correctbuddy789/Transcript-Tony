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
    """Extract YouTube video ID from various URL formats, including youtu.be and handling query parameters."""
    if not url:
        return None

    url = url.strip()
    parsed_url = urlparse(url)

    if 'youtu.be' in parsed_url.netloc:
        # Handle youtu.be short links
        path = parsed_url.path.lstrip('/')
        video_id = path.split('?')[0]  # Split on '?' and take the first part
        video_id = video_id.split('/')[0]  # Take first part in case there is any '/'
        return video_id

    elif 'youtube.com' in parsed_url.netloc:
        # Handle youtube.com links
        if '/watch' in parsed_url.path:
            query_params = parse_qs(parsed_url.query)
            return query_params.get('v', [None])[0]
        elif '/embed/' in parsed_url.path or '/v/' in parsed_url.path or '/live/' in parsed_url.path:
            path_parts = parsed_url.path.split('/')
            # Find the video ID, handling different path structures
            for part in reversed(path_parts):  # Iterate in reverse
                if part:  # Check for non-empty parts
                    return part
        elif 'shorts' in parsed_url.path:
            path_parts = parsed_url.path.split('/')
            return path_parts[-1]
    return None


def get_captions_from_pytube(video_id):
    """Try to get captions using PyTube"""
    try:
        yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
        captions = yt.captions

        if not captions or len(captions.all()) == 0:
            return False, "No captions available for this video"

        # Try to get English captions first
        caption_track = None

        # First try to get English
        for track in captions.all():
            if track.code.startswith(('en', 'a.en')):
                caption_track = track
                break

        # If no English, take any available caption
        if caption_track is None and captions.all():
            caption_track = captions.all()[0]

        if caption_track:
            transcript = caption_track.generate_srt_captions()
            # Convert SRT to plain text
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
    # Mimic a browser User-Agent
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',  # Add Accept-Language header
    })

    max_retries = 3
    retry_delay = 1  # Initial delay in seconds

    for attempt in range(max_retries):
        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            response = session.get(video_url)

            if response.status_code != 200:
                return False, f"Failed to access video page (status code: {response.status_code})"

            # Try to extract caption track info from the response

            # First check for English auto-generated captions
            caption_params = {'v': video_id, 'lang': 'en'}
            caption_url = f"https://www.youtube.com/api/timedtext"
            caption_response = session.get(caption_url, params=caption_params)
            if caption_response.status_code == 200 and caption_response.text:
                try:
                    root = ET.fromstring(caption_response.text)
                    transcript_text = " ".join([elem.text for elem in root.findall(".//text") if elem.text])
                    if transcript_text:
                        return True, transcript_text
                except Exception:
                    pass


            # Try to extract from captionTracks or playerCaptionsTracklistRenderer
            data_pattern = r'(?:"captionTracks":(\[.*?\])|"playerCaptionsTracklistRenderer":.*?(\[.*?\]))'
            matches = re.findall(data_pattern, response.text)
            caption_data = None

            for match_group in matches:
                for match in match_group:
                    if match:
                        try:
                            caption_data = json.loads(match)
                            break
                        except (json.JSONDecodeError, TypeError): # More specific exception handling
                            continue
                if caption_data:
                    break

            if not caption_data:
                return False, "No caption data found in video page"

            for track in caption_data:
                if "baseUrl" in track:
                    caption_url = track["baseUrl"]
                    # Get the captions
                    caption_response = session.get(caption_url)
                    if caption_response.status_code == 200: # No need to check .text here
                        try:
                            root = ET.fromstring(caption_response.text)
                            transcript_text = " ".join([elem.text for elem in root.findall(".//text") if elem.text is not None])
                            if transcript_text: # check if transcript is not empty
                                 return True, transcript_text
                        except ET.ParseError as xml_err:
                            return False, f"Failed to parse caption XML: {xml_err}"
            return False, "No suitable caption URL found"

        except requests.RequestException as e:  # Catch network-related errors
            error_msg = f"Network error: {e}"
            if attempt < max_retries - 1:
                st.warning(f"Attempt {attempt + 1} failed: {error_msg}. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                return False, error_msg
        except Exception as e: # Catch all other exception
            return False, f"An unexpected error occurred: {e}"

    return False, "Max retries exceeded" # Return message if all attempts failed

def sanitize_filename(name):
    """Create a safe filename from any input string"""
    if not name:
        return "transcript"

    # Remove illegal characters
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    # Replace spaces with underscores
    name = name.replace(" ", "_")
    # Ensure it's not too long
    name = name[:100]
    # Ensure we have a name
    return name if name else "transcript"


def main():
    st.set_page_config(page_title="YouTube Transcript Extractor", page_icon="📝")

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
            "

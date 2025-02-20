import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from youtube_transcript_api._transcripts import TranscriptListFetcher
from urllib.parse import urlparse, parse_qs
import zipfile
import io
import re
import requests
import json
import os


# Override the default fetcher to include cookies
class CustomTranscriptListFetcher(TranscriptListFetcher):
    def __init__(self):
        super().__init__()
        
    def fetch(self, video_id, proxies=None, cookies=None):
        """
        Fetch transcript list with optional cookies
        """
        url = 'https://www.youtube.com/watch'
        params = {'v': video_id}
        
        # Use cookies if provided
        if cookies:
            if isinstance(cookies, str) and os.path.exists(cookies):
                # Load cookies from file
                with open(cookies, 'r') as f:
                    cookies_dict = json.load(f)
            elif isinstance(cookies, dict):
                cookies_dict = cookies
            else:
                cookies_dict = None
        else:
            cookies_dict = None
            
        result = requests.get(url, params=params, proxies=proxies, cookies=cookies_dict)
        if result.status_code != 200:
            raise Exception(f'Failed to get transcript info: HTTP {result.status_code}')
            
        return result.text


def extract_video_id(video_url):
    """
    Extracts the video ID from a YouTube video URL.
    """
    try:
        # Clean the URL in case it contains mixed formats or additional parameters
        video_url = video_url.strip()
        
        # Handle URLs with playlist parameter or additional parameters
        if '&' in video_url:
            video_url = video_url.split('&')[0]
            
        parsed_url = urlparse(video_url)
        if parsed_url.netloc not in ['www.youtube.com', 'youtube.com', 'm.youtube.com', 'youtu.be']:
            return None
        if parsed_url.netloc in ['youtu.be']:
            return parsed_url.path[1:].split('?')[0]  # Remove query params from youtu.be URLs
        if parsed_url.query:
            query_params = parse_qs(parsed_url.query)
            video_ids = query_params.get('v')
            if video_ids:
                return video_ids[0]
        return None
    except Exception as e:
        st.error(f"Error parsing URL '{video_url}': {e}")
        return None


def get_youtube_transcript(video_url, use_cookies=True, language_preference=None):
    """
    Extracts the transcript from a YouTube video with better error handling and cookie support.
    """
    video_id = extract_video_id(video_url)
    if not video_id:
        error_message = f"Error: Could not extract video ID from the provided URL: '{video_url}'"
        return False, error_message, video_id

    try:
        # Use custom fetcher with cookies if requested
        fetcher = CustomTranscriptListFetcher() if use_cookies else None
        
        # Prepare language list - try user preference first, then English, then any
        languages = []
        if language_preference:
            languages.append(language_preference)
        if 'en' not in languages:
            languages.append('en')
            
        transcript_list = YouTubeTranscriptApi._get_transcript_list(
            video_id, 
            fetcher=fetcher,
            cookies={} if use_cookies else None  # Pass empty dict to enable cookies but not restrict to specific ones
        )
        
        # Try to get transcript in preferred language(s) first
        try:
            if languages:
                transcript = transcript_list.find_transcript(languages)
            else:
                # If no language preference, get the first available transcript
                transcript = transcript_list.find_transcript([])
        except NoTranscriptFound:
            # If preferred languages not found, try any language
            transcript = transcript_list.find_transcript([])
            
        transcript_data = transcript.fetch()
        transcript_text = ""
        for segment in transcript_data:
            transcript_text += segment['text'] + " "
            
        # Add source language information to the transcript
        source_language = transcript.language_code
        transcript_header = f"# Transcript (Source language: {source_language})\n\n"
        return True, transcript_header + transcript_text, video_id

    except NoTranscriptFound:
        error_message = f"No transcript available for video ID: '{video_id}'"
        return False, error_message, video_id
            
    except TranscriptsDisabled:
        error_message = f"Transcripts are disabled for video ID: '{video_id}'"
        return False, error_message, video_id
        
    except Exception as e:
        error_message = f"Error extracting transcript for video ID: '{video_id}': {e}"
        return False, error_message, video_id


def sanitize_filename(filename):
    """
    Sanitizes a filename by removing or replacing invalid characters.
    """
    filename = filename.strip()
    filename = re.sub(r'[\\/*?:"<>|]', '', filename)  # Remove invalid characters
    filename = filename.replace(" ", "_")  # Replace spaces with underscores
    if not filename:
        filename = "transcript_file"  # Default if filename becomes empty
    return filename


def parse_video_urls(input_text):
    """
    Parse a text area input that might contain multiple URLs in different formats.
    Returns a list of cleaned, individual URLs.
    """
    # First split by common line break characters
    lines = re.split(r'[\n\r]+', input_text.strip())
    
    urls = []
    for line in lines:
        # Split by common URL starts to handle cases where URLs are concatenated
        potential_urls = re.split(r'(https?://)', line)
        
        for i, part in enumerate(potential_urls):
            if part.lower() in ['http://', 'https://']:
                if i+1 < len(potential_urls):
                    urls.append(f"{part}{potential_urls[i+1]}")
    
    # If no URLs were found with the method above, try a more direct regex approach
    if not urls:
        urls = re.findall(r'(https?://[^\s]+)', input_text)
    
    return [url.strip() for url in urls if url.strip()]


def main():
    st.title("YouTube Transcript Extractor")
    st.markdown("Enter YouTube video URLs and desired filenames (optional) to extract transcripts.")

    video_urls_input = st.text_area(
        "Enter YouTube Video URLs (one per line):",
        placeholder="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://www.youtube.com/watch?v=another_video_id"
    )
    filenames_input = st.text_area(
        "Enter Desired Filenames (one per line, corresponding to URLs - optional):",
        placeholder="video1_name\nvideo2_name"
    )
    
    # Advanced options in expander
    with st.expander("Advanced Options"):
        use_cookies = st.checkbox("Use Cookie Support (helps with restricted videos)", value=True)
        language_preference = st.text_input("Preferred Language Code (leave empty for English or any available)", 
                                           placeholder="es, fr, de, ja, etc.")

    if st.button("Extract and Download Transcripts"):
        video_urls = parse_video_urls(video_urls_input)
        filenames = [name.strip() for name in filenames_input.strip().split('\n') if name.strip()]

        if not video_urls:
            st.warning("Please enter at least one valid YouTube video URL.")
        else:
            st.info(f"Found {len(video_urls)} URLs to process")
            
            # Display the parsed URLs so the user can verify
            with st.expander("Show detected URLs"):
                for i, url in enumerate(video_urls):
                    st.write(f"{i+1}. {url}")
            
            transcripts_data = []  # List to store (filename, transcript_text) tuples
            success_count = 0
            failure_count = 0

            for i, video_url in enumerate(video_urls):
                default_filename = f"transcript_{i+1}"
                output_filename_base = filenames[i] if i < len(filenames) else default_filename
                output_filename_base_sanitized = sanitize_filename(output_filename_base)
                output_filename = f"{output_filename_base_sanitized}.txt"

                with st.spinner(f"Extracting transcript for: {video_url}"):
                    success, transcript_text, video_id = get_youtube_transcript(
                        video_url, 
                        use_cookies=use_cookies,
                        language_preference=language_preference if language_preference else None
                    )
                    
                    if success:
                        success_count += 1
                        transcripts_data.append((output_filename, transcript_text))
                        st.markdown(f"✅ **Video {i+1}: {video_url}** (saved as `{output_filename}`)")
                        st.code(transcript_text[:500] + "..." if len(transcript_text) > 500 else transcript_text, language=None)
                        st.download_button(
                            label=f"Download Transcript {i+1}",
                            data=transcript_text,
                            file_name=output_filename,
                            mime="text/plain"
                        )
                    else:
                        failure_count += 1
                        st.markdown(f"❌ **Video {i+1}: {video_url}**")
                        st.error(transcript_text)  # Display the error message
                    
                    st.write("-" * 30)

            # Summary statistics
            st.write(f"### Summary: {success_count} succeeded, {failure_count} failed")
            
            if transcripts_data:  # If at least one transcript was extracted
                # Create Download All button
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for filename, transcript_text in transcripts_data:
                        zip_file.writestr(filename, transcript_text)
                zip_buffer.seek(0)  # Reset buffer to beginning for download

                st.download_button(
                    label=f"Download All {success_count} Transcripts as ZIP",
                    data=zip_buffer,
                    file_name="transcripts.zip",
                    mime="application/zip"
                )


if __name__ == "__main__":
    main()

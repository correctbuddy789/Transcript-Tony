import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from urllib.parse import urlparse, parse_qs
import zipfile
import io
import re
import json
import os
import requests

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


def get_youtube_transcript(video_url, language_preference=None):
    """
    Extracts the transcript from a YouTube video with better error handling.
    Uses direct API calls without custom fetcher.
    """
    video_id = extract_video_id(video_url)
    if not video_id:
        error_message = f"Error: Could not extract video ID from the provided URL: '{video_url}'"
        return False, error_message, video_id

    try:
        # Try to get transcript with specific languages
        languages = []
        if language_preference:
            languages.append(language_preference)
        if 'en' not in languages:
            languages.append('en')
            
        try:
            # First try with specified languages
            if languages:
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
            else:
                # Fall back to default language
                transcript = YouTubeTranscriptApi.get_transcript(video_id)
                
        except NoTranscriptFound:
            # If preferred languages not found, try any language
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            
        transcript_text = ""
        for segment in transcript:
            transcript_text += segment['text'] + " "
            
        return True, transcript_text, video_id

    except NoTranscriptFound:
        # Try fallback method - get list of available transcripts first
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            available_transcript = transcript_list.find_generated_transcript(languages=['en']) or \
                                  transcript_list.find_generated_transcript(languages=[]) or \
                                  transcript_list.find_manually_created_transcript(languages=['en']) or \
                                  transcript_list.find_manually_created_transcript(languages=[])
            
            if available_transcript:
                transcript_data = available_transcript.fetch()
                transcript_text = ""
                for segment in transcript_data:
                    transcript_text += segment['text'] + " "
                return True, transcript_text, video_id
            else:
                error_message = f"No transcript available for video ID: '{video_id}'"
                return False, error_message, video_id
                
        except Exception as e:
            error_message = f"No transcript available for video ID: '{video_id}' (Fallback failed: {str(e)})"
            return False, error_message, video_id
            
    except TranscriptsDisabled:
        # Try to get an automatically generated transcript as fallback
        try:
            # Try using list_transcripts which can sometimes access auto-generated ones
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            auto_transcript = next((t for t in transcript_list if t.is_generated), None)
            
            if auto_transcript:
                transcript_data = auto_transcript.fetch()
                transcript_text = ""
                for segment in transcript_data:
                    transcript_text += segment['text'] + " "
                return True, transcript_text, video_id
            else:
                error_message = f"Transcripts are disabled for video ID: '{video_id}'"
                return False, error_message, video_id
                
        except Exception:
            error_message = f"Transcripts are disabled for video ID: '{video_id}'"
            return False, error_message, video_id
        
    except Exception as e:
        error_message = f"Error extracting transcript for video ID: '{video_id}': {e}"
        return False, error_message, video_id


def try_alternative_transcript_method(video_id):
    """
    Alternative method to get transcripts by directly accessing YouTube's API.
    """
    try:
        # Try to directly use requests to fetch transcript data
        session = requests.Session()
        response = session.get(f"https://www.youtube.com/watch?v={video_id}")
        
        if response.status_code != 200:
            return False, f"Could not access video page, status code: {response.status_code}"
            
        # This is experimental and might need adjustments based on YouTube's API changes
        try:
            transcript_url = f"https://www.youtube.com/api/timedtext?v={video_id}&lang=en"
            transcript_response = session.get(transcript_url)
            
            if transcript_response.status_code == 200 and transcript_response.text:
                return True, "Successfully retrieved transcript using alternative method"
            else:
                return False, "Alternative transcript method failed"
                
        except Exception as e:
            return False, f"Alternative transcript fetch failed: {str(e)}"
            
    except Exception as e:
        return False, f"Alternative method failed: {str(e)}"


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
        language_preference = st.text_input("Preferred Language Code (leave empty for English or any available)", 
                                           placeholder="es, fr, de, ja, etc.")
        use_browser = st.checkbox("Experimental: Try to fetch from HTML (may work with some restricted videos)", value=False)

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
            
            # Version info
            st.info(f"Using youtube-transcript-api version: {YouTubeTranscriptApi.__version__ if hasattr(YouTubeTranscriptApi, '__version__') else 'Unknown'}")
            
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
                        language_preference=language_preference if language_preference else None
                    )
                    
                    # If standard method failed and experimental is enabled, try the alternative
                    if not success and use_browser and video_id:
                        st.warning(f"Standard extraction failed for {video_url}, trying experimental method...")
                        alt_success, alt_message = try_alternative_transcript_method(video_id)
                        if alt_success:
                            st.success(f"Experimental method succeeded: {alt_message}")
                            # Re-try with standard method after priming with browser access
                            success, transcript_text, _ = get_youtube_transcript(video_url)
                    
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
                        
                        # Provide more information about the video if extraction failed
                        if video_id:
                            st.info(f"Video ID: {video_id}")
                            st.markdown(f"This video may have restricted transcripts or doesn't have any available transcripts.")
                    
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
            
            # Troubleshooting information
            if failure_count > 0:
                st.markdown("""
                ## Why This Might Be Happening
                
                1. **No Available Transcripts**: Some YouTube videos don't have any transcripts available.
                2. **Owner Restrictions**: The video owner may have disabled transcript access.
                3. **Authentication Required**: Some videos require you to be logged in to access transcripts.
                4. **Geo-restrictions**: Transcript availability can vary by region.
                
                ### Using This App Locally
                If you've confirmed that transcripts work locally but not on Streamlit Cloud:
                
                ```python
                # Install dependencies
                pip install streamlit youtube-transcript-api
                
                # Save this app as app.py and run
                streamlit run app.py
                ```
                
                When running locally, your browser's cookies may allow access to transcripts that are restricted on Streamlit Cloud.
                """)


if __name__ == "__main__":
    main()

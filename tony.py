#Tushar Nain - V1.2

import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
import zipfile
import io
import re  # For sanitizing filenames


def extract_video_id(video_url):
    """
    Extracts the video ID from a YouTube video URL.
    """
    try:
        parsed_url = urlparse(video_url)
        if parsed_url.netloc not in ['www.youtube.com', 'youtube.com', 'm.youtube.com', 'youtu.be']:
            return None
        if parsed_url.netloc in ['youtu.be']:
            return parsed_url.path[1:]
        if parsed_url.query:
            query_params = parse_qs(parsed_url.query)
            video_ids = query_params.get('v')
            if video_ids:
                return video_ids[0]
        return None
    except Exception:
        return None


def get_youtube_transcript(video_url): # Removed output_filename as filenames are handled later
    """
    Extracts the English transcript from a YouTube video.
    Returns: tuple: (bool, str, str) - Success, transcript text, video ID (for error messages)
    """
    video_id = extract_video_id(video_url)
    if not video_id:
        error_message = f"Error: Could not extract video ID from the provided URL: '{video_url}'"
        st.error(error_message)
        return False, error_message, video_id

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        transcript_text = ""
        for segment in transcript:
            transcript_text += segment['text'] + " "
        return True, transcript_text, video_id

    except Exception as e:
        error_message = f"Error extracting transcript for video ID: '{video_id}': {e}"
        st.error(error_message)
        return False, error_message, video_id


def sanitize_filename(filename):
    """
    Sanitizes a filename by removing or replacing invalid characters.
    """
    filename = filename.strip()
    filename = re.sub(r'[\\/*?:"<>|]', '', filename)  # Remove or replace invalid characters
    filename = filename.replace(" ", "_") # Replace spaces with underscores
    if not filename:
        filename = "transcript_file" # Default if filename becomes empty after sanitization
    return filename


def main():
    st.title("YouTube Transcript Extractor")
    st.markdown("Enter YouTube video URLs and desired filenames (optional) to extract transcripts.")

    video_urls_input = st.text_area("Enter YouTube Video URLs (one per line):",
                                      placeholder="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://www.youtube.com/watch?v=another_video_id")
    filenames_input = st.text_area("Enter Desired Filenames (one per line, corresponding to URLs - optional [Layer_Interview Bucket_Company]):",
                                     placeholder="video1_name\nvideo2_name")

    if st.button("Extract and Download Transcripts"):
        video_urls = [url.strip() for url in video_urls_input.strip().split('\n') if url.strip()]
        filenames = [name.strip() for name in filenames_input.strip().split('\n')]

        if not video_urls:
            st.warning("Please enter at least one YouTube video URL.")
        else:
            transcripts_data = [] # List to store (filename, transcript_text) tuples

            for i, video_url in enumerate(video_urls):
                default_filename = f"transcript_{i+1}.txt"
                output_filename_base = filenames[i] if i < len(filenames) and filenames[i] else default_filename
                output_filename_base_sanitized = sanitize_filename(output_filename_base)
                output_filename = f"{output_filename_base_sanitized}_{i+1}.txt" # Append index for uniqueness

                with st.spinner(f"Extracting transcript for: {video_url}"):
                    success, transcript_text, video_id = get_youtube_transcript(video_url) # Removed output_filename argument
                    if success:
                        transcripts_data.append((output_filename, transcript_text)) # Store data for Download All
                        st.markdown(f"**Transcript for Video {i+1}: {video_url}** (saved as `{output_filename}`)")
                        st.code(transcript_text[:500] + "..." if len(transcript_text) > 500 else transcript_text, language=None)
                        st.download_button(
                            label=f"Download Transcript {i+1} (as {output_filename})",
                            data=transcript_text,
                            file_name=output_filename,
                            mime="text/plain"
                        )
                        st.write("-" * 30)

            if transcripts_data: # If at least one transcript was extracted
                # Create Download All button
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for filename, transcript_text in transcripts_data:
                        zip_file.writestr(filename, transcript_text)
                zip_buffer.seek(0) # Reset buffer to beginning for download

                st.download_button(
                    label="Download All Transcripts as ZIP",
                    data=zip_buffer,
                    file_name="transcripts.zip",
                    mime="application/zip"
                )


if __name__ == "__main__":
    main()

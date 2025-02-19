import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs

def extract_video_id(video_url):
    """
    Extracts the video ID from a YouTube video URL.

    Args:
     video_url (str): The full YouTube video URL.

    Returns:
     str or None: The video ID if found, None otherwise.
    """
    try:
        parsed_url = urlparse(video_url)
        if parsed_url.netloc not in ['www.youtube.com', 'youtube.com', 'm.youtube.com', 'youtu.be']:
            return None  # Not a YouTube URL

        if parsed_url.netloc in ['youtu.be']:
            return parsed_url.path[1:] # Extract from short URLs like youtu.be/VIDEO_ID

        if parsed_url.query:
            query_params = parse_qs(parsed_url.query)
            video_ids = query_params.get('v')
            if video_ids:
                return video_ids[0]  # Get the first video ID if multiple are present (unlikely in typical URLs)
        return None # Could not extract video ID

    except Exception:
        return None # Error during URL parsing


def get_youtube_transcript(video_url, output_filename="transcript.txt"):
    """
    Extracts the English transcript from a YouTube video given its URL and saves it to a text file.

    Args:
     video_url (str): The full YouTube video URL.
     output_filename (str, optional): The name of the file to save the transcript to.
                  Defaults to "transcript.txt".
    Returns:
     tuple: (bool, str) - True if transcript extracted, False otherwise, and the transcript text.
          Prints error messages to the console if something goes wrong.
    """
    video_id = extract_video_id(video_url)
    if not video_id:
        error_message = f"Error: Could not extract video ID from the provided URL: '{video_url}'\n" \
                        f"Please make sure you provided a valid YouTube video URL."
        st.error(error_message) # Use st.error to display error in Streamlit
        return False, error_message

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)

        # Format the transcript into a single string
        transcript_text = ""
        for segment in transcript:
            transcript_text += segment['text'] + " "

        # Save the transcript to a text file (removed file saving for streamlit, will return text)
        # with open(output_filename, 'w', encoding='utf-8') as file:
        #  file.write(transcript_text)

        success_message = f"Transcript for video URL '{video_url}' (video ID: '{video_id}') extracted."
        st.success(success_message) # Use st.success to display success in Streamlit
        return True, transcript_text

    except Exception as e:
        error_message = f"Error extracting transcript for video URL '{video_url}' (video ID: '{video_id}'): {e}\n" \
                        f"Please make sure the video URL is correct and the video has English subtitles available."
        st.error(error_message) # Use st.error to display error in Streamlit
        return False, error_message


def main():
    st.title("Tony the Transcript Extractor")
    st.markdown("Enter YouTube video URLs to extract transcripts.")

    video_urls_input = st.text_area("Enter YouTube Video URLs (one per line):",
                                      placeholder="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://www.youtube.com/watch?v=another_video_id")

    if st.button("Extract Transcripts"):
        video_urls = [url.strip() for url in video_urls_input.strip().split('\n') if url.strip()] # Split by newline and remove empty lines

        if not video_urls:
            st.warning("Please enter at least one YouTube video URL.")
        else:
            st.session_state['transcripts'] = {} # Use session state to store transcripts

            for i, video_url in enumerate(video_urls):
                output_filename = f"transcript_{i+1}.txt" # Default filename for streamlit

                with st.spinner(f"Extracting transcript for: {video_url}"): # Show spinner while processing
                    success, transcript_text = get_youtube_transcript(video_url, output_filename)
                    if success:
                        st.session_state['transcripts'][video_url] = transcript_text # Store in session state
                        st.markdown(f"**Transcript for Video {i+1}: {video_url}**") # Header for each transcript
                        st.code(transcript_text[:500] + "..." if len(transcript_text) > 500 else transcript_text, language=None) # Display snippet or full transcript, using st.code for text formatting
                        st.download_button(
                            label=f"Download Transcript {i+1}",
                            data=transcript_text,
                            file_name=output_filename,
                            mime="text/plain"
                        )
                        st.write("-" * 30) # Separator for better readability


if __name__ == "__main__":
    main()

import streamlit as st
import re
from pytube import YouTube
import os
import zipfile
import io
from urllib.parse import urlparse, parse_qs
import xml.etree.ElementTree as ET
import requests
import json


def extract_video_id(url):
    """Extract YouTube video ID from various URL formats"""
    if not url:
        return None
        
    url = url.strip()
    
    # Handle youtu.be short links
    if 'youtu.be' in url:
        parts = url.split('/')
        for part in parts:
            if part and 'youtu.be' not in part and '?' not in part:
                return part.split('?')[0]
    
    # Handle youtube.com links
    parsed_url = urlparse(url)
    if 'youtube.com' in parsed_url.netloc:
        if '/watch' in parsed_url.path:
            query = parse_qs(parsed_url.query)
            return query.get('v', [None])[0]
        elif '/embed/' in parsed_url.path or '/v/' in parsed_url.path:
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
    """Try to get captions using direct API access"""
    try:
        # First try to get a list of available caption tracks
        session = requests.Session()
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        response = session.get(video_url)
        
        if response.status_code != 200:
            return False, f"Failed to access video page (status code: {response.status_code})"
        
        # Try to extract caption track info from the response
        try:
            # First check for English auto-generated captions
            caption_url = f"https://www.youtube.com/api/timedtext?v={video_id}&lang=en"
            caption_response = session.get(caption_url)
            
            if caption_response.status_code == 200 and caption_response.text:
                # Parse the XML
                try:
                    root = ET.fromstring(caption_response.text)
                    transcript_text = " ".join([elem.text for elem in root.findall(".//text") if elem.text])
                    if transcript_text:
                        return True, transcript_text
                except Exception:
                    pass
            
            # Try to extract the serializedShareEntity which sometimes contains caption URLs
            data_pattern = r'(?:"captionTracks":(\[.*?\])|"playerCaptionsTracklistRenderer":.*?(\[.*?\]))'
            matches = re.findall(data_pattern, response.text)
            
            caption_data = None
            for match_group in matches:
                for match in match_group:
                    if match:
                        try:
                            caption_data = json.loads(match)
                            break
                        except:
                            continue
                if caption_data:
                    break
                    
            if not caption_data:
                return False, "No caption data found in video page"
                
            # Extract the first available caption URL
            caption_url = None
            for track in caption_data:
                if "baseUrl" in track:
                    caption_url = track["baseUrl"]
                    break
                    
            if not caption_url:
                return False, "No caption URL found in video data"
                
            # Get the captions
            caption_response = session.get(caption_url)
            if caption_response.status_code != 200:
                return False, f"Failed to get captions (status code: {caption_response.status_code})"
                
            # Parse the XML
            try:
                root = ET.fromstring(caption_response.text)
                transcript_text = " ".join([elem.text for elem in root.findall(".//text") if elem.text])
                return True, transcript_text
            except Exception as xml_err:
                return False, f"Failed to parse caption XML: {str(xml_err)}"
        
        except Exception as e:
            return False, f"API extraction error: {str(e)}"
            
    except Exception as e:
        return False, f"General API error: {str(e)}"


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
            "Extraction Method",
            ["Auto (try all methods)", "PyTube", "Direct API Access"],
            index=0
        )
    
    if st.button("Extract Transcripts"):
        if not url_input.strip():
            st.warning("Please enter at least one YouTube URL.")
            return
            
        # Process URLs
        urls = [url.strip() for url in url_input.strip().split('\n') if url.strip()]
        names = [name.strip() for name in name_input.strip().split('\n') if name.strip()]
        
        st.info(f"Processing {len(urls)} video(s)...")
        
        # Use session state to store results
        if 'results' not in st.session_state:
            st.session_state.results = []
        else:
            st.session_state.results = []
            
        success_count = 0
        fail_count = 0
        
        for i, url in enumerate(urls):
            # Get filename
            custom_name = names[i] if i < len(names) else f"video_{i+1}"
            sanitized_name = sanitize_filename(custom_name)
            filename = f"{sanitized_name}.txt"
            
            # Extract video ID
            video_id = extract_video_id(url)
            if not video_id:
                st.error(f"❌ Could not extract video ID from URL: {url}")
                fail_count += 1
                continue
                
            st.markdown(f"### Processing: {url}")
            st.write(f"Video ID: {video_id}")
            
            # Extract transcript based on selected method
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
            
            # Display results
            if success:
                success_count += 1
                st.success(f"✅ Successfully extracted transcript for {url}")
                st.session_state.results.append((filename, transcript, video_id))
                
                with st.expander("Preview Transcript"):
                    st.code(transcript[:1000] + ("..." if len(transcript) > 1000 else ""))
                
                st.download_button(
                    label=f"Download {filename}",
                    data=transcript,
                    file_name=filename,
                    mime="text/plain"
                )
            else:
                fail_count += 1
                st.error(f"❌ Failed to extract transcript for {url}")
                st.write(f"Reason: {error_msg}")
            
            st.markdown("---")
        
        # Summary
        st.markdown(f"## Summary: {success_count} succeeded, {fail_count} failed")
        
        # Create ZIP download if we have results
        if st.session_state.results:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file_name, content, _ in st.session_state.results:
                    zip_file.writestr(file_name, content)
            zip_buffer.seek(0)
            
            st.download_button(
                label=f"Download All Transcripts ({success_count})",
                data=zip_buffer,
                file_name="youtube_transcripts.zip",
                mime="application/zip"
            )
        
        # Display troubleshooting info if any failures
        if fail_count > 0:
            st.markdown("""
            ## Troubleshooting
            
            If transcripts are failing to extract, consider:
            
            1. **Privacy Restrictions**: Some videos have disabled captions/transcripts
            2. **Regional Restrictions**: Some videos may not be available with captions in your region
            3. **Authentication**: When running locally, your browser authentication might allow access to more transcripts
            
            For reliable extraction of transcripts from videos with restrictions, consider:
            - Running this app locally (where your browser cookies can be used)
            - Using third-party services that can download videos with captions
            """)


# Install requirements: streamlit pytube requests
if __name__ == '__main__':
    main()

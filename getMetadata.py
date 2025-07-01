from time import sleep
from urllib.parse import urlparse, parse_qs
import requests
import json
import base64
import datetime
import hashlib
import re
import time
import pyotp
from typing import Dict, Any, List, Tuple

AUTH_TOKEN = None
AUTH_TOKEN_EXPIRY = 0
SECRETS = None
SECRETS_EXPIRY = 0

def spotify_decode_secret(raw_secret):
    k = [(e ^ t % 33 + 9) for t, e in enumerate(raw_secret)]
    uint8_secret = [int(x) for x in "".join([str(x) for x in k]).encode("utf-8")]
    bytes_secret = bytes(uint8_secret)
    return base64.b32encode(bytes_secret).decode("ascii")

def spotify_totp(decoded_secret, timestamp):
    return pyotp.hotp.HOTP(s=decoded_secret, digits=6, digest=hashlib.sha1).at(int(timestamp / 30))

def get_spotify_secrets():
    global SECRETS, SECRETS_EXPIRY
    if not SECRETS or SECRETS_EXPIRY < time.time():
        response = requests.get("https://open.spotify.com", 
                              headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"}, 
                              timeout=10)
        response.raise_for_status()
        
        match = re.search(r"\"([\w/:\-\.]*/web-player\.\w*\.js)\"", response.content.decode("utf-8"))
        if not match:
            raise SpotifyWebsiteParserException("Could not find assets URL")
        
        response = requests.get(match.group(1), timeout=10)
        response.raise_for_status()
        
        match = re.search(r"\'({\"validUntil\":[^']*)\'", response.content.decode("utf-8"))
        if not match:
            raise SpotifyWebsiteParserException("Could not find secrets in assets")
        
        data = json.loads(match.group(1))
        SECRETS = data["secrets"]
        SECRETS_EXPIRY = datetime.datetime.fromisoformat(data["validUntil"].split(".")[0]).timestamp()
    return SECRETS

token_url = 'https://open.spotify.com/api/token'
playlist_base_url = 'https://api.spotify.com/v1/playlists/{}'
album_base_url = 'https://api.spotify.com/v1/albums/{}'
track_base_url = 'https://api.spotify.com/v1/tracks/{}'
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://open.spotify.com/',
    'Origin': 'https://open.spotify.com'
}

class SpotifyInvalidUrlException(Exception):
    pass

class SpotifyWebsiteParserException(Exception):
    pass

def parse_uri(uri):
    u = urlparse(uri)
    if u.netloc == "embed.spotify.com":
        if not u.query:
            raise SpotifyInvalidUrlException("ERROR: url {} is not supported".format(uri))
        qs = parse_qs(u.query)
        return parse_uri(qs['uri'][0])

    if not u.scheme and not u.netloc:
        return {"type": "playlist", "id": u.path}

    if u.scheme == "spotify":
        parts = uri.split(":")
    else:
        if u.netloc != "open.spotify.com" and u.netloc != "play.spotify.com":
            raise SpotifyInvalidUrlException("ERROR: url {} is not supported".format(uri))
        parts = u.path.split("/")

    if parts[1] == "embed":
        parts = parts[1:]

    l = len(parts)
    if l == 3 and parts[1] in ["album", "track", "playlist"]:
        return {"type": parts[1], "id": parts[2]}
    if l == 5 and parts[3] == "playlist":
        return {"type": parts[3], "id": parts[4]}

    raise SpotifyInvalidUrlException("ERROR: unable to determine Spotify URL type or type is unsupported.")

def get_json_from_api(api_url, access_token):
    headers.update({'Authorization': 'Bearer {}'.format(access_token)})
    
    req = requests.get(api_url, headers=headers, timeout=10)

    if req.status_code == 429:
        seconds = int(req.headers.get("Retry-After", "5")) + 1
        print(f"INFO: rate limited! Sleeping for {seconds} seconds")
        sleep(seconds)
        return None

    if req.status_code != 200:
        raise SpotifyWebsiteParserException(f"ERROR: {api_url} gave us not a 200. Instead: {req.status_code}")
        
    return req.json()

def get_access_token():
    global AUTH_TOKEN, AUTH_TOKEN_EXPIRY
    if not AUTH_TOKEN or AUTH_TOKEN_EXPIRY < time.time():
        secrets = get_spotify_secrets()
        decoded_secret = spotify_decode_secret(secrets[0]["secret"])
        version = secrets[0]["version"]
        c_time = int(time.time() * 1000)
        totp = spotify_totp(decoded_secret, c_time / 1000)

        params = {
            "reason": "init",
            "productType": "web-player",
            "totp": totp,
            "totpServer": totp,
            "totpVer": version,
        }
        
        req = requests.get(token_url, params=params, headers={
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "dnt": "1",
            "priority": "u=1, i",
            "referer": "https://open.spotify.com/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        }, timeout=10)
        
        if req.status_code != 200:
            return {"error": f"Failed to get access token. Status code: {req.status_code}"}
        
        token_data = req.json()
        AUTH_TOKEN = token_data.get("accessToken")
        AUTH_TOKEN_EXPIRY = token_data.get("accessTokenExpirationTimestampMs", 0) / 1000
        return {"accessToken": AUTH_TOKEN}
    return {"accessToken": AUTH_TOKEN}

def fetch_tracks_in_batches(url: str, access_token: str, batch_size: int = 100, delay: float = 1.0) -> Tuple[List[Dict[str, Any]], int]:
    all_tracks = []
    current_batch = 0
    
    while url:
        print(f"Batch : {current_batch}")
        
        url_parts = url.split("offset=")
        if len(url_parts) > 1:
            offset_part = url_parts[1].split("&")[0]
            print(f"Offset : {offset_part}")
        print("-------------")
        
        track_data = get_json_from_api(url, access_token)
        if not track_data:
            break
        
        items = track_data.get('items', [])
        all_tracks.extend(items)
        
        url = track_data.get('next')
        if url and "&locale=" in url:
            url = url.split("&locale=")[0]
            
        if url and delay > 0:
            sleep(delay)
        
        current_batch += 1
        
    return all_tracks, current_batch

def get_raw_spotify_data(spotify_url, batch: bool = False, delay: float = 1.0):
    url_info = parse_uri(spotify_url)
    token = get_access_token()
    
    if "error" in token:
        return token
    
    access_token = token["accessToken"]
    raw_data = {}
    
    if url_info['type'] == "playlist":
        try:
            playlist_data = get_json_from_api(
                playlist_base_url.format(url_info["id"]), 
                access_token
            )
            if not playlist_data:
                return {"error": "Failed to get playlist data"}
                
            raw_data = playlist_data
            total_tracks = playlist_data.get('tracks', {}).get('total', 0)
            
            if batch:
                tracks_url = f'https://api.spotify.com/v1/playlists/{url_info["id"]}/tracks?limit=100'
                tracks, num_batches = fetch_tracks_in_batches(tracks_url, access_token, 100, delay)
                raw_data['tracks']['items'] = tracks
                raw_data['_batch_count'] = num_batches
                raw_data['_batch_enabled'] = True
                
                if len(tracks) < total_tracks:
                    last_offset = len(tracks)
                    remaining_tracks = []
                    
                    while last_offset < total_tracks:
                        print(f"Batch : {num_batches}")
                        print(f"Offset : {last_offset}")
                        print("-------------")
                        
                        remainder_url = f'https://api.spotify.com/v1/playlists/{url_info["id"]}/tracks?offset={last_offset}&limit=100'
                        track_data = get_json_from_api(remainder_url, access_token)
                        
                        if not track_data or not track_data.get('items'):
                            break
                            
                        items = track_data.get('items', [])
                        remaining_tracks.extend(items)
                        
                        if len(items) < 100:
                            break
                            
                        last_offset += len(items)
                        num_batches += 1
                        
                        if delay > 0:
                            sleep(delay)
                    
                    tracks.extend(remaining_tracks)
                    raw_data['tracks']['items'] = tracks
                    raw_data['_batch_count'] = num_batches
            else:
                tracks = []
                tracks_url = f'https://api.spotify.com/v1/playlists/{url_info["id"]}/tracks?limit=100'
                while tracks_url:
                    track_data = get_json_from_api(tracks_url, access_token)
                    if not track_data:
                        break
                        
                    tracks.extend(track_data['items'])
                    tracks_url = track_data.get('next')
                    if tracks_url and "&locale=" in tracks_url:
                        tracks_url = tracks_url.split("&locale=")[0]
                    
                raw_data['tracks']['items'] = tracks
                raw_data['_batch_enabled'] = False
                
        except Exception as e:
            return {"error": f"Failed to get playlist data: {str(e)}"}
            
    elif url_info["type"] == "album":
        try:
            album_data = get_json_from_api(
                album_base_url.format(url_info["id"]),
                access_token
            )
            if not album_data:
                return {"error": "Failed to get album data"}
                
            album_data['_token'] = access_token
            raw_data = album_data
            total_tracks = album_data.get('total_tracks', 0)
            
            if batch:
                tracks_url = f'{album_base_url.format(url_info["id"])}/tracks?limit=50'
                tracks, num_batches = fetch_tracks_in_batches(tracks_url, access_token, 50, delay)
                raw_data['tracks']['items'] = tracks
                raw_data['_batch_count'] = num_batches
                raw_data['_batch_enabled'] = True
                
                if len(tracks) < total_tracks:
                    last_offset = len(tracks)
                    remaining_tracks = []
                    
                    while last_offset < total_tracks:
                        print(f"Batch : {num_batches}")
                        print(f"Offset : {last_offset}")
                        print("-------------")
                        
                        remainder_url = f'{album_base_url.format(url_info["id"])}/tracks?offset={last_offset}&limit=50'
                        track_data = get_json_from_api(remainder_url, access_token)
                        
                        if not track_data or not track_data.get('items'):
                            break
                            
                        items = track_data.get('items', [])
                        remaining_tracks.extend(items)
                        
                        if len(items) < 50:
                            break
                            
                        last_offset += len(items)
                        num_batches += 1
                        
                        if delay > 0:
                            sleep(delay)
                    
                    tracks.extend(remaining_tracks)
                    raw_data['tracks']['items'] = tracks
                    raw_data['_batch_count'] = num_batches
            else:
                tracks = []
                tracks_url = f'{album_base_url.format(url_info["id"])}/tracks?limit=50'
                while tracks_url:
                    track_data = get_json_from_api(tracks_url, access_token)
                    if not track_data:
                        break
                        
                    tracks.extend(track_data['items'])
                    tracks_url = track_data.get('next')
                    if tracks_url and "&locale=" in tracks_url:
                        tracks_url = tracks_url.split("&locale=")[0]
                    
                raw_data['tracks']['items'] = tracks
                raw_data['_batch_enabled'] = False
                
        except Exception as e:
            return {"error": f"Failed to get album data: {str(e)}"}
                
    elif url_info["type"] == "track":
        try:
            track_data = get_json_from_api(
                track_base_url.format(url_info["id"]),
                access_token
            )
            if not track_data:
                return {"error": "Failed to get track data"}
                
            raw_data = track_data
        except Exception as e:
            return {"error": f"Failed to get track data: {str(e)}"}

    return raw_data

def format_track_data(track_data):
    artists = []
    artist_ids = []
    for artist in track_data.get('artists', []):
        artists.append(artist['name'])
        artist_ids.append(artist['id'])
    
    image_url = track_data.get('album', {}).get('images', [{}])[0].get('url', '') if track_data.get('album', {}).get('images') else ''
    
    return {
        "track": {
            "id": track_data.get('id', ''),
            "uri": track_data.get('uri', ''),
            "artists": ", ".join(artists),
            "artist_ids": artist_ids,
            "name": track_data.get('name', ''),
            "album_id": track_data.get('album', {}).get('id', ''),
            "album_name": track_data.get('album', {}).get('name', ''),
            "duration_ms": track_data.get('duration_ms', 0),
            "images": image_url,
            "release_date": track_data.get('album', {}).get('release_date', ''),
            "track_number": track_data.get('track_number', 0),
            "isrc": track_data.get('external_ids', {}).get('isrc', '')
        }
    }

def format_album_data(album_data):
    artists = []
    artist_ids = []
    for artist in album_data.get('artists', []):
        artists.append(artist['name'])
        artist_ids.append(artist['id'])
    
    image_url = album_data.get('images', [{}])[0].get('url', '') if album_data.get('images') else ''
    
    track_list = []
    for track in album_data.get('tracks', {}).get('items', []):
        track_id = track.get('id', '')
        try:
            track_data = get_json_from_api(
                track_base_url.format(track_id),
                album_data.get('_token', '')
            )
            if track_data:
                formatted_track = format_track_data(track_data)
                track_list.append(formatted_track['track'])
            else:
                track_artists = []
                track_artist_ids = []
                for artist in track.get('artists', []):
                    track_artists.append(artist['name'])
                    track_artist_ids.append(artist['id'])
                    
                track_list.append({
                    "id": track.get('id', ''),
                    "uri": track.get('uri', ''),
                    "artists": ", ".join(track_artists),
                    "artist_ids": track_artist_ids,
                    "name": track.get('name', ''),
                    "album_id": album_data.get('id', ''),
                    "album_name": album_data.get('name', ''),
                    "duration_ms": track.get('duration_ms', 0),
                    "images": image_url,
                    "release_date": album_data.get('release_date', ''),
                    "track_number": track.get('track_number', 0),
                    "isrc": track.get('external_ids', {}).get('isrc', '')
                })
        except:
            continue
    
    album_info = {
        "id": album_data.get('id', ''),
        "uri": album_data.get('uri', ''),
        "total_tracks": album_data.get('total_tracks', 0),
        "name": album_data.get('name', ''),
        "release_date": album_data.get('release_date', ''),
        "artists": ", ".join(artists),
        "artist_ids": artist_ids,
        "images": image_url
    }
    
    if album_data.get('_batch_enabled', False):
        album_info["batch"] = f"{album_data.get('_batch_count', 1)}"
    
    return {
        "album_info": album_info,
        "track_list": track_list
    }

def format_playlist_data(playlist_data):
    image_url = playlist_data.get('images', [{}])[0].get('url', '') if playlist_data.get('images') else ''
    
    track_list = []
    for item in playlist_data.get('tracks', {}).get('items', []):
        track = item.get('track', {})
        if not track:
            continue
            
        artists = []
        artist_ids = []
        for artist in track.get('artists', []):
            artists.append(artist['name'])
            artist_ids.append(artist['id'])
            
        track_image = ''
        if track.get('album', {}).get('images'):
            track_image = track.get('album', {}).get('images', [{}])[0].get('url', '')
        
        track_list.append({
            "id": track.get('id', ''),
            "uri": track.get('uri', ''),
            "artists": ", ".join(artists),
            "artist_ids": artist_ids,
            "name": track.get('name', ''),
            "album_id": track.get('album', {}).get('id', ''),
            "album_name": track.get('album', {}).get('name', ''),
            "duration_ms": track.get('duration_ms', 0),
            "images": track_image,
            "release_date": track.get('album', {}).get('release_date', ''),
            "track_number": track.get('track_number', 0),
            "isrc": track.get('external_ids', {}).get('isrc', '')
        })
    
    playlist_info = {
        "id": playlist_data.get('id', ''),
        "uri": playlist_data.get('uri', ''),
        "tracks": {"total": playlist_data.get('tracks', {}).get('total', 0)},
        "followers": {"total": playlist_data.get('followers', {}).get('total', 0)},
        "owner": {
            "id": playlist_data.get('owner', {}).get('id', ''),
            "uri": playlist_data.get('owner', {}).get('uri', ''),
            "display_name": playlist_data.get('owner', {}).get('display_name', ''),
            "name": playlist_data.get('name', ''),
            "images": image_url
        }
    }
    
    if playlist_data.get('_batch_enabled', False):
        playlist_info["batch"] = f"{playlist_data.get('_batch_count', 1)}"
    
    return {
        "playlist_info": playlist_info,
        "track_list": track_list
    }

def process_spotify_data(raw_data, data_type):
    if not raw_data or "error" in raw_data:
        return {"error": "Invalid data provided"}
        
    try:
        if data_type == "track":
            return format_track_data(raw_data)
        elif data_type == "album":
            return format_album_data(raw_data)
        elif data_type == "playlist":
            return format_playlist_data(raw_data)
        else:
            return {"error": "Invalid data type"}
    except Exception as e:
        return {"error": f"Error processing data: {str(e)}"}

def get_filtered_data(spotify_url, batch=False, delay=1.0):
    raw_data = get_raw_spotify_data(spotify_url, batch=batch, delay=delay)
    if raw_data and "error" not in raw_data:
        url_info = parse_uri(spotify_url)
        filtered_data = process_spotify_data(raw_data, url_info['type'])
        return filtered_data
    return {"error": "Failed to get raw data"}

if __name__ == '__main__':
    playlist = "https://open.spotify.com/playlist/37i9dQZEVXbNG2KDcFcKOF"
    album = "https://open.spotify.com/album/6J84szYCnMfzEcvIcfWMFL"
    song = "https://open.spotify.com/track/7so0lgd0zP2Sbgs2d7a1SZ"
    
    filtered_playlist = get_filtered_data(playlist, batch=True, delay=0.1)
    print(json.dumps(filtered_playlist, indent=2))
    
    filtered_album = get_filtered_data(album)
    print(json.dumps(filtered_album, indent=2))
    
    filtered_track = get_filtered_data(song)
    print(json.dumps(filtered_track, indent=2))
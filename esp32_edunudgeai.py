# Import library yang diperlukan
from machine import Pin, SoftI2C, ADC, RTC
import ssd1306
import dht
import time
import network
from umqtt.simple import MQTTClient
import _thread
import urequests
import ntptime
import socket
import ujson
import machine
import gc

# ========== KONFIGURASI HARDWARE ==========
# OLED Display
SCREEN_WIDTH = 128  # Lebar layar OLED dalam pixel
SCREEN_HEIGHT = 64  # Tinggi layar OLED dalam pixel
OLED_ADDR = 0x3C    # Alamat I2C OLED

# Konfigurasi Pin
DHTPIN = Pin(4)     # Pin untuk sensor DHT11
DHTTYPE = dht.DHT11 # Tipe sensor DHT
PIR_PIN = Pin(27, Pin.IN)  # Pin input untuk sensor PIR
LDR_PIN = ADC(Pin(34))  # Pin ADC untuk sensor cahaya (LDR)
LDR_PIN.atten(ADC.ATTN_11DB)  # Atur rentang pengukuran ADC
LDR_PIN.width(ADC.WIDTH_12BIT)  # Gunakan resolusi 12-bit

SOUND_PIN = ADC(Pin(35))  # Pin ADC untuk sensor suara
SOUND_PIN.atten(ADC.ATTN_11DB)
SOUND_PIN.width(ADC.WIDTH_12BIT)

# Pin output untuk komponen lain
BUZZER_PIN = Pin(23, Pin.OUT)  # Buzzer
LED_PIR = Pin(5, Pin.OUT)      # LED indikator PIR
LED_WIFI = Pin(18, Pin.OUT)    # LED indikator WiFi
LED_LIGHT = Pin(19, Pin.OUT)   # LED indikator cahaya

# ========== KALIBRASI SENSOR ==========
LIGHT_MIN = 0      # Nilai minimum LDR (gelap total)
LIGHT_MAX = 4095   # Nilai maksimum LDR (cahaya terang)
SOUND_MIN = 200    # Nilai minimum suara (sunyi)
SOUND_MAX = 3500   # Nilai maksimum suara (bising)

# ========== KONFIGURASI KONEKSI ==========
CONFIG_FILE = "config.json"  # File konfigurasi untuk data sensitif
WIFI_CONFIG_FILE = "wifi_config.json"  # File untuk konfigurasi WiFi

# ========== FUNGSI UTILITAS ==========
def read_config():
    """Membaca konfigurasi dari file"""
    try:
        with open(CONFIG_FILE, "r") as f:
            config = ujson.load(f)
            # Validasi struktur config
            if not all(k in config for k in ["mqtt", "api"]):
                raise ValueError("Struktur config file tidak valid")
            return config
    except Exception as e:
        print("Gagal membaca file konfigurasi:", e)
        # Return config default kosong jika file tidak ada
        return {
            "mqtt": {
                "server": "",
                "token": "",
                "device_label": "",
                "topic": ""
            },
            "api": {
                "url": "",
                "key": ""
            }
        }

def read_wifi_config():
    """Membaca konfigurasi WiFi dari file"""
    try:
        with open(WIFI_CONFIG_FILE, "r") as f:
            config = ujson.load(f)
            return config.get("ssid", ""), config.get("password", "")
    except Exception as e:
        print("Gagal membaca wifi config:", e)
        return "", ""
    
# ========== INISIALISASI KONFIGURASI ==========
try:
    config = read_config()
    
    # MQTT Configuration - diambil dari file config
    MQTT_SERVER = config["mqtt"]["server"]
    MQTT_TOKEN = config["mqtt"]["token"]
    DEVICE_LABEL = config["mqtt"]["device_label"]
    TOPIC = config["mqtt"]["topic"]

    # MongoDB API Configuration - diambil dari file config
    FLASK_API_URL = config["api"]["url"]
    API_KEY = config["api"]["key"]

    # Validasi konfigurasi penting
    if not all([MQTT_SERVER, MQTT_TOKEN, FLASK_API_URL]):
        raise ValueError("Konfigurasi penting kosong, periksa config.json")
except Exception as e:
    print("Error inisialisasi konfigurasi:", e)
    # Tampilkan error di OLED
    i2c = SoftI2C(scl=Pin(22), sda=Pin(21))
    display = ssd1306.SSD1306_I2C(SCREEN_WIDTH, SCREEN_HEIGHT, i2c, addr=OLED_ADDR)
    display.fill(0)
    display.text("Error Config!", 0, 0)
    display.text(str(e)[:20], 0, 10)
    display.show()
    time.sleep(10)
    machine.reset()

MONGODB_INTERVAL = 5  # Interval pengiriman data ke MongoDB (detik)
UBIDOTS_INTERVAL = 5  # Interval pengiriman data ke Ubidots (detik)

# ========== VARIABEL GLOBAL ==========
wifi_connected = False  # Status koneksi WiFi
mqtt_client = None      # Objek klien MQTT
ap_mode_active = False  # Status mode Access Point
last_mongodb_send = 0   # Waktu terakhir kirim ke MongoDB
last_ubidots_send = 0    # Waktu terakhir kirim ke Ubidots
last_pir_time = 0        # Waktu terakhir deteksi PIR
pir_debounce_time = 3000 # Waktu debounce untuk PIR (ms)
last_ntp_sync_time = 0   # Waktu terakhir sinkronisasi NTP
ntp_sync_interval = 3600 # Interval sinkronisasi NTP (detik)
last_sensor_data = {     # Menyimpan data sensor terakhir
    "temp": 0.0,
    "hum": 0.0,
    "light": 0.0,
    "sound": 0.0,
    "motion": False,
    "timestamp": "1970-01-01 00:00:00 WIB"
}

# Inisialisasi Hardware
i2c = SoftI2C(scl=Pin(22), sda=Pin(21))  # Inisialisasi I2C
display = ssd1306.SSD1306_I2C(SCREEN_WIDTH, SCREEN_HEIGHT, i2c, addr=OLED_ADDR)
dht_sensor = dht.DHT11(DHTPIN)  # Inisialisasi sensor DHT11

# Inisialisasi RTC (Real-Time Clock)
rtc = RTC()

# Inisialisasi variabel wlan
wlan = None  # Objek jaringan WiFi

def save_wifi_config(ssid, password):
    """Menyimpan konfigurasi WiFi ke file"""
    try:
        config = {"ssid": ssid, "password": password}
        with open(WIFI_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    except Exception as e:
        print("Gagal menyimpan wifi config:", e)

def sync_ntp():
    """Sinkronisasi waktu dari server NTP"""
    global last_ntp_sync_time
    try:
        ntptime.settime()
        last_ntp_sync_time = time.time()
        print("Waktu berhasil disinkronisasi dari NTP")
    except Exception as e:
        print("Gagal menyinkronisasi waktu dari NTP:", e)
        # Set waktu default jika NTP gagal
        rtc.datetime((2025, 1, 1, 0, 0, 0, 0, 0))

def get_formatted_time():
    """Mendapatkan waktu yang diformat dalam WIB (UTC+7)"""
    (year, month, day, _, hour, minute, second, _) = rtc.datetime()
    
    # Konversi ke WIB (UTC+7)
    hour += 7
    if hour >= 24:
        hour -= 24
        day += 1
    
    # Periksa overflow hari/bulan/tahun
    days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        days_in_month[1] = 29
    
    if day > days_in_month[month - 1]:
        day = 1
        month += 1
        if month > 12:
            month = 1
            year += 1
    
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d} WIB".format(
        year, month, day, hour, minute, second)

def to_percentage(value, min_val, max_val):
    """Konversi nilai sensor ke persentase"""
    value = max(min(value, max_val), min_val)
    percentage = (value - min_val) / (max_val - min_val) * 100
    return round(percentage, 1)

def update_display(temp, hum, light, sound, motion, wifi_status, db_status):
    """Update tampilan OLED dengan data sensor"""
    display.fill(0)
    
    # Baris 1: Status koneksi
    display.text(f"WiFi: {'ON' if wifi_status else 'OFF'}", 0, 0)
    display.text(f"DB: {'OK' if db_status else 'ERR'}", 80, 0)
    
    # Baris 2-6: Data sensor
    display.text(f"Temp  : {temp:.1f}C", 0, 10)
    display.text(f"Humi  : {hum:.1f}%", 0, 20)
    display.text(f"Light : {light:.0f}%", 0, 30)
    display.text(f"Sound : {sound:.0f}%", 0, 40)
    display.text(f"Motion: {'YES' if motion else 'NO'}", 0, 50)
    
    # Baris 7: Waktu
    display.text(get_formatted_time(), 0, 60)
    
    display.show()

# ========== FUNGSI KONEKSI ==========
def connect_wifi():
    """Menghubungkan ke jaringan WiFi"""
    global wifi_connected, wlan, ap_mode_active
    try:
        ssid, password = read_wifi_config()
        
        if not ssid or not password:
            start_ap_mode()
            return
        
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        wlan.disconnect()
        wlan.connect(ssid, password)
        start_time = time.ticks_ms()
        
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), start_time) > 10000:
                print("WiFi gagal terhubung! Mulai mode AP.")
                start_ap_mode()
                return
            time.sleep(0.5)
        
        print("WiFi Terhubung!")
        wifi_connected = True
        ap_mode_active = False
        LED_WIFI.value(1)
        sync_ntp()
    except Exception as e:
        print("Error connect_wifi:", e)
        start_ap_mode()

def start_ap_mode():
    """Memulai mode Access Point untuk konfigurasi WiFi"""
    global wlan, ap_mode_active
    try:
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid="EduNudge-AI", password="1231231239", authmode=network.AUTH_WPA_WPA2_PSK)
        print("Mode AP aktif. SSID: EduNudge-AI, Password: 1231231239")
        ap_mode_active = True
        
        # Tampilkan instruksi di OLED
        display.fill(0)
        display.text("Mode AP Aktif", 0, 0)
        display.text("SSID: EduNudge-AI", 0, 10)
        display.text("Pass: 1231231239", 0, 20)
        display.text("Akses:", 0, 30)
        display.text("192.168.4.1/config", 0, 40)
        display.text("di browser Anda!", 0, 50)
        display.show()
        
        start_web_server()
    except Exception as e:
        print("Error start_ap_mode:", e)
        machine.reset()

def start_web_server():
    """Web server untuk konfigurasi WiFi dalam mode AP"""
    global ap_mode_active
    try:
        addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
        s = socket.socket()
        s.bind(addr)
        s.listen(1)
        print("Web server berjalan di http://192.168.4.1")
        
        while ap_mode_active:
            conn, addr = s.accept()
            try:
                request = conn.recv(1024).decode("utf-8")
                
                if "GET /config" in request:
                    response = """HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n
                    <h1>Konfigurasi WiFi</h1>
                    <form method="post" action="/save">
                        SSID: <input type="text" name="ssid"><br>
                        Password: <input type="password" name="password"><br>
                        <input type="submit" value="Simpan">
                    </form>"""
                    conn.send(response.encode("utf-8"))
                elif "POST /save" in request:
                    body = request.split("\r\n\r\n")[1]
                    params = body.split("&")
                    ssid = params[0].split("=")[1]
                    password = params[1].split("=")[1]
                    save_wifi_config(ssid, password)
                    response = """HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n
                    <h1>Konfigurasi WiFi Disimpan!</h1>
                    <p>ESP32 akan restart dan mencoba terhubung ke WiFi.</p>"""
                    conn.send(response.encode("utf-8"))
                    conn.close()
                    time.sleep(2)
                    machine.reset()
                else:
                    conn.send("HTTP/1.1 404 Not Found\r\n\r\n".encode("utf-8"))
            except Exception as e:
                print("Error handling request:", e)
            finally:
                conn.close()
    except Exception as e:
        print("Error start_web_server:", e)
        machine.reset()

def connect_mqtt():
    """Menghubungkan ke broker MQTT"""
    global mqtt_client
    try:
        mqtt_client = MQTTClient("ESP32_Client", MQTT_SERVER, user=MQTT_TOKEN, password="")
        mqtt_client.connect()
        print("MQTT Terhubung!")
        return True
    except Exception as e:
        print("Gagal menghubungkan MQTT:", e)
        mqtt_client = None
        return False

# ========== DATA HANDLING ==========
def send_to_mongodb(temp, hum, light, motion, sound):
    """Mengirim data ke MongoDB melalui API"""
    global last_mongodb_send, last_sensor_data
    
    try:
        timestamp = get_formatted_time()
        payload = {
            "temp": temp,
            "hum": hum,
            "light": light,
            "motion": motion,
            "sound": sound,
            "timestamp": timestamp,
            "device": "ESP32-Sensor"
        }
        
        # Simpan data terakhir
        last_sensor_data = {
            "temp": temp,
            "hum": hum,
            "light": light,
            "sound": sound,
            "motion": motion,
            "timestamp": timestamp
        }
        
        headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}
        response = urequests.post(FLASK_API_URL, json=payload, headers=headers)
        response.close()
        last_mongodb_send = time.time()
        print("MongoDB: Data sent")
        return True
    except Exception as e:
        print("MongoDB Error:", e)
        if "ECONNABORTED" in str(e):
            connect_wifi()
        return False

def send_to_ubidots(temp, hum, light, motion, sound):
    """Mengirim data ke Ubidots melalui MQTT"""
    global last_ubidots_send, mqtt_client, last_sensor_data
    
    if not mqtt_client and not connect_mqtt():
        return False
    
    try:
        payload = f'{{"temp":{temp:.1f},"hum":{hum:.1f},"light":{light:.1f},"sound":{sound:.1f},"motion":{motion}}}'
        mqtt_client.publish(TOPIC, payload)
        last_ubidots_send = time.time()
        
        # Simpan data terakhir
        last_sensor_data = {
            "temp": temp,
            "hum": hum,
            "light": light,
            "sound": sound,
            "motion": motion,
            "timestamp": get_formatted_time()
        }
        
        print("Ubidots: Data sent")
        return True
    except Exception as e:
        print("Ubidots Error:", e)
        mqtt_client = None
        return False

# ========== THREAD MONITORING ==========
def check_wifi_status():
    """Thread untuk memantau status WiFi"""
    global wifi_connected, mqtt_client, last_ntp_sync_time, wlan, ap_mode_active
    
    while True:
        try:
            if wlan and wlan.isconnected():
                if not wifi_connected:
                    print("WiFi Kembali Terhubung!")
                    wifi_connected = True
                    LED_WIFI.value(1)
                    connect_mqtt()
                    sync_ntp()
                
                # Sinkronisasi ulang waktu
                if time.time() - last_ntp_sync_time > ntp_sync_interval:
                    sync_ntp()
            else:
                if wifi_connected:
                    print("WiFi Terputus!")
                    wifi_connected = False
                    LED_WIFI.value(0)
            
            time.sleep(1)
        except Exception as e:
            print("Error check_wifi_status:", e)
            time.sleep(5)

# Mulai thread untuk monitoring WiFi
_thread.start_new_thread(check_wifi_status, ())

# ========== MAIN LOOP ==========
def main():
    """Fungsi utama program"""
    global last_pir_time, last_mongodb_send, last_ubidots_send, last_sensor_data
    
    # Inisialisasi Sistem
    print("Memulai sistem...")
    display.fill(0)
    display.text("EduNudge AI", 0, 0)
    display.text("Memulai Sistem...", 0, 10)
    display.show()
    time.sleep(2)
    
    # Koneksi awal
    connect_wifi()
    if wifi_connected:
        connect_mqtt()
    
    # Inisialisasi last_sensor_data dengan nilai default
    last_sensor_data = {
        "temp": 0.0,
        "hum": 0.0,
        "light": 0.0,
        "sound": 0.0,
        "motion": False,
        "timestamp": get_formatted_time()
    }
    
    while True:
        try:
            if not ap_mode_active:
                # Baca sensor DHT
                temp, hum = last_sensor_data["temp"], last_sensor_data["hum"]
                try:
                    dht_sensor.measure()
                    temp = dht_sensor.temperature()
                    hum = dht_sensor.humidity()
                except OSError as e:
                    print("Error baca DHT:", e)
                    # Gunakan nilai terakhir jika gagal baca
                
                # Baca sensor lainnya
                motion = PIR_PIN.value()
                light_raw = LDR_PIN.read()
                light = to_percentage(light_raw, LIGHT_MIN, LIGHT_MAX)
                sound_raw = SOUND_PIN.read()
                sound = to_percentage(sound_raw, SOUND_MIN, SOUND_MAX)
                
                # Deteksi gerakan dengan debounce
                current_time = time.ticks_ms()
                if motion and time.ticks_diff(current_time, last_pir_time) > pir_debounce_time:
                    last_pir_time = current_time
                    LED_PIR.value(1)
                    BUZZER_PIN.value(1)
                    time.sleep(0.5)
                    BUZZER_PIN.value(0)
                else:
                    LED_PIR.value(0)
                
                # Indikator cahaya rendah
                if light < 15:
                    LED_LIGHT.value(1)
                    BUZZER_PIN.value(1)
                    time.sleep(0.5)
                    BUZZER_PIN.value(0)
                else:
                    LED_LIGHT.value(0)
                
                # Update tampilan OLED
                db_status = time.time() - last_mongodb_send < 60 if wifi_connected else False
                update_display(temp, hum, light, sound, motion, wifi_connected, db_status)
                
                # Kirim data jika WiFi terhubung
                current_time = time.time()
                if wifi_connected:
                    if current_time - last_mongodb_send > MONGODB_INTERVAL:
                        if send_to_mongodb(temp, hum, light, motion, sound):
                            last_mongodb_send = current_time
                    
                    if current_time - last_ubidots_send > UBIDOTS_INTERVAL:
                        if send_to_ubidots(temp, hum, light, motion, sound):
                            last_ubidots_send = current_time
                
                # Simpan data terakhir
                last_sensor_data = {
                    "temp": temp,
                    "hum": hum,
                    "light": light,
                    "sound": sound,
                    "motion": motion,
                    "timestamp": get_formatted_time()
                }
                
                gc.collect()
            
            time.sleep(1)
        except Exception as e:
            print("Error main loop:", e)
            # Tampilkan data terakhir yang tersimpan jika terjadi error
            update_display(
                last_sensor_data["temp"],
                last_sensor_data["hum"],
                last_sensor_data["light"],
                last_sensor_data["sound"],
                last_sensor_data["motion"],
                wifi_connected,
                False
            )
            time.sleep(5)

if __name__ == "__main__":
    main()
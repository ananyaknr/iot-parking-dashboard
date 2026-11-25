#pragma once
#define WIFI_ENTERPRISE 0
// For ChulaWiFi use configure-enterprise.ps1 and a verified university CA certificate.
// That script supplies EAP username, CA, server name and an initial UTC clock value.
// Run scripts/configure-wifi.ps1 locally. Never paste credentials into chat.
const char WIFI_SSID[] = "YOUR_2_4_GHZ_WIFI";
const char WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";
const char MQTT_HOST[] = "10.203.188.159";
const uint16_t MQTT_PORT = 1883;
const char MQTT_USERNAME[] = "parking";
const char MQTT_PASSWORD[] = "GENERATED_LOCAL_MQTT_PASSWORD";

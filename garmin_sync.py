import os
import json
import requests
from datetime import datetime, timedelta, timezone
from garminconnect import Garmin
from supabase import create_client

GARMIN_EMAIL     = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD  = os.environ["GARMIN_PASSWORD"]
MAKE_WEBHOOK_URL = os.environ["MAKE_WEBHOOK_URL"]
SUPABASE_URL     = os.environ["SUPABASE_URL"]
SUPABASE_KEY     = os.environ["SUPABASE_KEY"]

def get_last_activity_id(supabase):
    result = supabase.table("actividades").select("garmin_id").order("fecha", desc=True).limit(1).execute()
    if result.data:
        return result.data[0]["garmin_id"]
    return None

def parse_duration(duration_str):
    if not duration_str:
        return None
    try:
        parts = str(duration_str).split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(float(parts[1]))
        return int(float(duration_str))
    except:
        return None

def sync_activity(activity, garmin_client, supabase):
    activity_id = str(activity.get("activityId", ""))

    # Verificar si ya existe
    existing = supabase.table("actividades").select("id").eq("garmin_id", activity_id).execute()
    if existing.data:
        print(f"Actividad {activity_id} ya existe, saltando.")
        return

    # Detalles completos
    details = garmin_client.get_activity_details(activity_id)
    splits  = garmin_client.get_activity_splits(activity_id)
    hr_data = garmin_client.get_heart_rates(activity.get("startTimeLocal", "")[:10])

    summary = details.get("summaryDTO", {})
    sport   = activity.get("activityType", {}).get("typeKey", "running")

    # Zonas de FC
    hr_zones = activity.get("heartRateZones", [])
    zona = lambda i: int(hr_zones[i].get("secsInZone", 0)) if len(hr_zones) > i else None

    # Splits por km
    splits_data = []
    if splits and "lapDTOs" in splits:
        for lap in splits["lapDTOs"]:
            splits_data.append({
                "km":       lap.get("lapIndex"),
                "pace":     round(lap.get("averageSpeed", 0), 2),
                "fc_avg":   lap.get("averageHR"),
                "distancia": round(lap.get("distance", 0) / 1000, 2)
            })

    row = {
        "garmin_id":                   activity_id,
        "fecha":                       activity.get("startTimeGMT"),
        "tipo":                        sport,
        "distancia_km":                round(activity.get("distance", 0) / 1000, 2),
        "duracion_seg":                parse_duration(summary.get("elapsedDuration")),
        "pace_avg":                    round(summary.get("averageSpeed", 0), 2),
        "fc_avg":                      activity.get("averageHR"),
        "fc_max":                      activity.get("maxHR"),
        "calorias":                    activity.get("calories"),
        "elevacion_m":                 activity.get("elevationGain"),
        "cadencia_avg":                activity.get("averageRunningCadenceInStepsPerMinute"),
        "vo2max":                      activity.get("vO2MaxValue"),
        "training_load":               activity.get("activityTrainingLoad"),
        "training_effect_aerobico":    activity.get("aerobicTrainingEffect"),
        "training_effect_anaerobico":  activity.get("anaerobicTrainingEffect"),
        "recovery_time_h":             activity.get("recoveryTime"),
        "training_status":             activity.get("trainingStatus"),
        "hrv_status":                  activity.get("hrvStatus"),
        "body_battery_inicio":         activity.get("startBodyBattery"),
        "tiempo_zona1_seg":            zona(0),
        "tiempo_zona2_seg":            zona(1),
        "tiempo_zona3_seg":            zona(2),
        "tiempo_zona4_seg":            zona(3),
        "tiempo_zona5_seg":            zona(4),
        "splits_json":                 splits_data,
    }

    # Guardar en Supabase
    supabase.table("actividades").insert(row).execute()
    print(f"Actividad {activity_id} guardada: {sport} {row['distancia_km']}km")

    # Mandar a Make.com para que Claude analice
    requests.post(MAKE_WEBHOOK_URL, json=row, timeout=30)
    print(f"Actividad enviada a Make.com")

def main():
    print("Conectando a Garmin Connect...")
    garmin = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    garmin.login()
    print("Login exitoso")

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Revisar últimas 24 horas
    end   = datetime.now(timezone.utc)
    start = end - timedelta(hours=25)

    activities = garmin.get_activities_by_date(
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        "running"
    )

    if not activities:
        print("No hay actividades nuevas.")
        return

    print(f"Encontradas {len(activities)} actividades, procesando...")
    for activity in activities:
        sync_activity(activity, garmin, supabase)

if __name__ == "__main__":
    main()

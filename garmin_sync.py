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

def ms_to_pace(speed_ms):
    """Convierte m/s a min/km"""
    if not speed_ms or speed_ms == 0:
        return None
    pace_min_km = (1000 / speed_ms) / 60
    return round(pace_min_km, 2)

def sync_activity(activity, garmin_client, supabase):
    activity_id = str(activity.get("activityId", ""))

    existing = supabase.table("actividades").select("id").eq("garmin_id", activity_id).execute()
    if existing.data:
        print(f"Actividad {activity_id} ya existe, saltando.")
        return

    details = garmin_client.get_activity_details(activity_id)
    splits  = garmin_client.get_activity_splits(activity_id)

    summary = details.get("summaryDTO", {})
    print("DEBUG activity keys:", list(activity.keys()))
print("DEBUG summary keys:", list(summary.keys()))
print("DEBUG averageSpeed:", activity.get("averageSpeed"), summary.get("averageSpeed"))
print("DEBUG duration:", activity.get("duration"), summary.get("elapsedDuration"), summary.get("movingDuration"))
print("DEBUG cadencia:", activity.get("averageRunningCadenceInStepsPerMinute"))
    sport   = activity.get("activityType", {}).get("typeKey", "running")

    # Duración
    duracion = summary.get("elapsedDuration") or summary.get("movingDuration") or activity.get("duration")
    if duracion:
        duracion = int(float(duracion))

    # Pace en min/km (Garmin manda m/s)
    speed_avg  = summary.get("averageSpeed") or activity.get("averageSpeed")
    speed_best = summary.get("maxSpeed") or activity.get("maxSpeed")
    pace_avg   = ms_to_pace(speed_avg)
    pace_mejor = ms_to_pace(speed_best)

    # Cadencia (Garmin manda pasos totales, dividir entre 2)
    cadencia_raw = activity.get("averageRunningCadenceInStepsPerMinute")
    cadencia = round(cadencia_raw / 2, 1) if cadencia_raw else None

    # Zonas de FC
    hr_zones = activity.get("heartRateZones", [])
    zona = lambda i: float(hr_zones[i].get("secsInZone", 0)) if len(hr_zones) > i else None

    # Splits por km
    splits_data = []
    if splits and "lapDTOs" in splits:
        for lap in splits["lapDTOs"]:
            lap_speed = lap.get("averageSpeed", 0)
            splits_data.append({
                "km":        lap.get("lapIndex"),
                "pace":      ms_to_pace(lap_speed),
                "fc_avg":    lap.get("averageHR"),
                "distancia": round(lap.get("distance", 0) / 1000, 2)
            })

    row = {
        "garmin_id":                   activity_id,
        "fecha":                       activity.get("startTimeGMT"),
        "tipo":                        sport,
        "distancia_km":                round(activity.get("distance", 0) / 1000, 2),
        "duracion_seg":                duracion,
        "pace_avg":                    pace_avg,
        "pace_mejor":                  pace_mejor,
        "fc_avg":                      activity.get("averageHR"),
        "fc_max":                      activity.get("maxHR"),
        "calorias":                    activity.get("calories"),
        "elevacion_m":                 activity.get("elevationGain"),
        "cadencia_avg":                cadencia,
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

    supabase.table("actividades").insert(row).execute()
    print(f"✓ Actividad guardada: {sport} {row['distancia_km']}km | pace {pace_avg} min/km | FC {row['fc_avg']}")

    requests.post(MAKE_WEBHOOK_URL, json=row, timeout=30)
    print(f"✓ Enviada a Make.com")

def main():
    print("Conectando a Garmin Connect...")
    garmin = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    garmin.login()
    print("Login exitoso")

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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

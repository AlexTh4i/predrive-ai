import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { AlertTriangle, Compass, Gauge, MapPin, Navigation, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { Empty, ErrorState, Loading, PageHeading, StatusBadge, eventLabels } from '../components/ui';
import { useFeed } from '../hooks/useLiveFeed';
import { errorMessage } from '../hooks/useResource';
import { formatClock, formatDateTime } from '../lib/format';
import type { LiveVehicleLocation, LocationTrailAlertPin, LocationTrailResponse } from '../types';

const DEFAULT_CENTER: [number, number] = [14.0583, 108.2772];
const DEFAULT_ZOOM = 6;

function stateColor(state: LiveVehicleLocation['state']): string {
  if (state === 'CRITICAL') return '#dc2626';
  if (state === 'DROWSINESS_SIGNS' || state === 'DISTRACTED') return '#d97706';
  if (state === 'DISCONNECTED' || state === 'OFFLINE') return '#64748b';
  return '#009a44';
}

export function FleetMap() {
  const { drivers: liveDrivers } = useFeed();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedDriverId = searchParams.get('driverId') || '';
  const requestedEventId = searchParams.get('eventId') || '';

  const [vehicles, setVehicles] = useState<LiveVehicleLocation[]>([]);
  const [selectedDriverId, setSelectedDriverId] = useState<string>(requestedDriverId);
  const [selectedEventId, setSelectedEventId] = useState<string>(requestedEventId);
  const [trail, setTrail] = useState<LocationTrailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [trailLoading, setTrailLoading] = useState(false);
  const [error, setError] = useState('');

  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const vehicleLayerRef = useRef<L.LayerGroup | null>(null);
  const trailLayerRef = useRef<L.LayerGroup | null>(null);
  const alertMarkersRef = useRef<Map<string, L.CircleMarker>>(new Map());

  const loadLocations = useCallback(async (signal?: AbortSignal) => {
    try {
      setError('');
      const list = await api.getLiveLocations(signal);
      setVehicles(list);
      setSelectedDriverId((current) => {
        if (current && list.some((item) => item.driverId === current)) return current;
        if (requestedDriverId && list.some((item) => item.driverId === requestedDriverId)) return requestedDriverId;
        return list[0]?.driverId ?? '';
      });
    } catch (err) {
      if (!signal?.aborted) setError(errorMessage(err));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [requestedDriverId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadLocations(controller.signal);
    return () => controller.abort();
  }, [loadLocations]);

  // Merge real-time SSE driver_state location updates into vehicle list
  const mergedVehicles = useMemo(() => {
    const byDriver = new Map<string, LiveVehicleLocation>();
    for (const item of vehicles) {
      byDriver.set(item.driverId, item);
    }
    for (const liveDrv of liveDrivers) {
      if (!liveDrv.location) continue;
      const prev = byDriver.get(liveDrv.driverId);
      byDriver.set(liveDrv.driverId, {
        driverId: liveDrv.driverId,
        driverName: liveDrv.fullName,
        vehicleId: prev?.vehicleId ?? null,
        vehicleName: liveDrv.vehicleName,
        state: liveDrv.state,
        sessionId: liveDrv.sessionId,
        lat: liveDrv.location.lat,
        lng: liveDrv.location.lng,
        speedKmh: liveDrv.location.speedKmh ?? prev?.speedKmh ?? null,
        headingDeg: liveDrv.location.headingDeg ?? prev?.headingDeg ?? null,
        at: liveDrv.location.at,
      });
    }
    return [...byDriver.values()];
  }, [liveDrivers, vehicles]);

  // Load route trail + alert pins when selected driver changes
  useEffect(() => {
    if (!selectedDriverId) {
      setTrail(null);
      return;
    }
    const controller = new AbortController();
    setTrailLoading(true);
    void api
      .getLocationTrail({ driverId: selectedDriverId }, controller.signal)
      .then((res) => {
        setTrail(res);
      })
      .catch(() => {
        if (!controller.signal.aborted) setTrail(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setTrailLoading(false);
      });
    return () => controller.abort();
  }, [selectedDriverId]);

  // Initialize Leaflet + OpenStreetMap (no API key needed)
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;
    const map = L.map(mapContainerRef.current, {
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: true,
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    vehicleLayerRef.current = L.layerGroup().addTo(map);
    trailLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      vehicleLayerRef.current = null;
      trailLayerRef.current = null;
    };
  }, [loading]);

  // Render live vehicle markers
  useEffect(() => {
    const layer = vehicleLayerRef.current;
    const map = mapRef.current;
    if (!layer || !map) return;

    layer.clearLayers();
    for (const veh of mergedVehicles) {
      const isSelected = veh.driverId === selectedDriverId;
      const color = stateColor(veh.state);
      const marker = L.circleMarker([veh.lat, veh.lng], {
        radius: isSelected ? 10 : 8,
        color: '#ffffff',
        weight: 2.5,
        fillColor: color,
        fillOpacity: 0.95,
      });
      const speedText = veh.speedKmh != null ? `${Math.round(veh.speedKmh)} km/h` : 'Chưa rõ tốc độ';
      marker.bindPopup(
        `<strong>${veh.vehicleName}</strong><br/>Tài xế: ${veh.driverName}<br/>Tốc độ: ${speedText}<br/>Cập nhật: ${formatClock(veh.at)}`,
      );
      marker.on('click', () => {
        setSelectedDriverId(veh.driverId);
        setSelectedEventId('');
        setSearchParams({ driverId: veh.driverId }, { replace: true });
      });
      marker.addTo(layer);
    }
  }, [mergedVehicles, selectedDriverId, setSearchParams]);

  // Render selected driver's route polyline + clickable alert pins
  useEffect(() => {
    const layer = trailLayerRef.current;
    const map = mapRef.current;
    if (!layer || !map) return;

    map.closePopup();
    layer.clearLayers();
    alertMarkersRef.current.clear();

    if (!trail) return;

    if (trail.points.length >= 2) {
      const latlngs: [number, number][] = trail.points.map((pt) => [pt.lat, pt.lng]);
      const polyline = L.polyline(latlngs, {
        color: '#0284c7',
        weight: 4,
        opacity: 0.85,
      });
      polyline.addTo(layer);
      if (!selectedEventId) {
        map.fitBounds(polyline.getBounds(), { padding: [32, 32], maxZoom: 13 });
      }
    } else if (trail.points.length === 1 && !selectedEventId) {
      map.setView([trail.points[0].lat, trail.points[0].lng], 12);
    }

    for (const alert of trail.alerts) {
      const isCrit = alert.level === 'CRITICAL';
      const pin = L.circleMarker([alert.lat, alert.lng], {
        radius: selectedEventId === alert.eventId ? 12 : 9,
        color: isCrit ? '#7f1d1d' : '#78350f',
        weight: 2.5,
        fillColor: isCrit ? '#ef4444' : '#f59e0b',
        fillOpacity: 1,
      });
      pin.bindPopup(
        `<strong>${eventLabels[alert.type]} (${isCrit ? 'Nguy hiểm' : 'Cảnh báo'})</strong><br/>` +
          `${alert.driverName} · ${alert.vehicleName}<br/>` +
          `Thời điểm: ${formatDateTime(alert.occurredAt)}`,
      );
      pin.on('click', () => {
        setSelectedEventId(alert.eventId);
        setSearchParams({ driverId: trail.driverId, eventId: alert.eventId }, { replace: true });
      });
      pin.addTo(layer);
      alertMarkersRef.current.set(alert.eventId, pin);
    }

    if (selectedEventId) {
      const targetPin = alertMarkersRef.current.get(selectedEventId);
      const targetAlert = trail.alerts.find((a) => a.eventId === selectedEventId);
      if (targetPin && targetAlert) {
        map.setView([targetAlert.lat, targetAlert.lng], 14);
        targetPin.openPopup();
      }
    }
  }, [selectedEventId, setSearchParams, trail]);

  function focusAlertPin(alert: LocationTrailAlertPin) {
    setSelectedEventId(alert.eventId);
    setSearchParams({ driverId: alert.driverId, eventId: alert.eventId }, { replace: true });
  }

  return (
    <div className="stack">
      <PageHeading
        title="Bản đồ hành trình đội xe"
        description="Vị trí trực tiếp, tốc độ di chuyển, vệt hành trình và điểm phát sinh cảnh báo trên tuyến"
        actions={
          <button className="button button-secondary" type="button" onClick={() => void loadLocations()}>
            <RefreshCw size={15} aria-hidden /> Làm mới vị trí
          </button>
        }
      />

      {loading ? (
        <Loading label="Đang tải vị trí đội xe…" />
      ) : error ? (
        <ErrorState message={error} retry={() => void loadLocations()} />
      ) : mergedVehicles.length === 0 ? (
        <div className="card">
          <Empty
            title="Chưa có tọa độ GPS nào được ghi nhận"
            description="Bật 'Cho phép chia sẻ vị trí' trong Cài đặt hệ thống và xác nhận quyền vị trí trên ứng dụng tài xế để hiển thị đội xe trực tiếp."
          />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <section className="card lg:col-span-2" aria-label="Bản đồ trực tuyến">
            <div className="section-head">
              <div>
                <h2>Bản đồ OpenStreetMap</h2>
                <p className="muted">
                  Đang theo dõi {mergedVehicles.length} xe · Bấm vào xe hoặc cảnh báo để xem đúng vị trí trên tuyến.
                </p>
              </div>
              {trailLoading && <small className="muted">Đang tải vệt hành trình…</small>}
            </div>
            <div
              ref={mapContainerRef}
              data-testid="fleet-leaflet-map"
              style={{ width: '100%', height: '420px', borderRadius: '12px', overflow: 'hidden', zIndex: 0 }}
            />
          </section>

          <section className="card stack" aria-label="Danh sách xe và cảnh báo trên tuyến">
            <div>
              <label className="block text-sm font-medium mb-1" htmlFor="map-driver-select">
                Chọn xe / tài xế xem vệt hành trình
              </label>
              <select
                id="map-driver-select"
                className="w-full"
                value={selectedDriverId}
                onChange={(e) => {
                  const nextId = e.target.value;
                  setSelectedDriverId(nextId);
                  setSelectedEventId('');
                  setSearchParams(nextId ? { driverId: nextId } : {}, { replace: true });
                }}
              >
                {mergedVehicles.map((item) => (
                  <option key={item.driverId} value={item.driverId}>
                    {item.vehicleName} — {item.driverName}
                  </option>
                ))}
              </select>
            </div>

            {selectedDriverId && (() => {
              const activeVeh = mergedVehicles.find((v) => v.driverId === selectedDriverId);
              if (!activeVeh) return null;
              return (
                <div className="rounded-xl border border-slate-200 p-3 text-sm space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <strong>{activeVeh.vehicleName}</strong>
                    <StatusBadge state={activeVeh.state} />
                  </div>
                  <p className="muted">{activeVeh.driverName}</p>
                  <div className="flex flex-wrap gap-3 text-xs text-slate-600">
                    <span className="inline-flex items-center gap-1">
                      <Gauge size={14} aria-hidden />
                      {activeVeh.speedKmh != null ? `${Math.round(activeVeh.speedKmh)} km/h` : '0 km/h'}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Compass size={14} aria-hidden />
                      {activeVeh.lat.toFixed(4)}, {activeVeh.lng.toFixed(4)}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Navigation size={14} aria-hidden />
                      {trail ? `${trail.points.length} điểm lộ trình` : '—'}
                    </span>
                  </div>
                </div>
              );
            })()}

            <div className="space-y-2">
              <h3 className="text-sm font-semibold flex items-center gap-1.5">
                <AlertTriangle size={15} aria-hidden /> Cảnh báo gắn tọa độ trên tuyến
              </h3>
              {!trail || trail.alerts.length === 0 ? (
                <p className="muted text-sm">Chưa có cảnh báo gắn tọa độ trên lộ trình này.</p>
              ) : (
                <ul className="space-y-2" data-testid="trail-alert-list">
                  {trail.alerts.map((alert) => {
                    const active = selectedEventId === alert.eventId;
                    return (
                      <li key={alert.eventId}>
                        <button
                          type="button"
                          onClick={() => focusAlertPin(alert)}
                          className={`w-full text-left rounded-xl border p-2.5 text-sm transition ${
                            active ? 'border-emerald-600 bg-emerald-50/60' : 'border-slate-200 hover:bg-slate-50'
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-1">
                            <strong>{eventLabels[alert.type]}</strong>
                            <span className={`severity ${alert.level === 'CRITICAL' ? 'tone-red' : 'tone-amber'}`}>
                              {alert.level === 'CRITICAL' ? 'Nguy hiểm' : 'Cảnh báo'}
                            </span>
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                            <span className="inline-flex items-center gap-1">
                              <MapPin size={12} aria-hidden />
                              {alert.lat.toFixed(4)}, {alert.lng.toFixed(4)}
                            </span>
                            <span>· {formatClock(alert.occurredAt)}</span>
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

import { useEffect, useRef } from 'react';
import { CircleMarker, Polygon, useMap, useMapEvents } from 'react-leaflet';
import type { LatLngExpression } from 'leaflet';

interface Props {
  drawing: boolean;
  points: LatLngExpression[];
  onAddPoint: (lat: number, lng: number) => void;
}

/** Fit map to bounds once (e.g. loaded saved boundary) — not while user is drawing. */
export function MapInitialBounds({ bounds }: { bounds: LatLngExpression[] | null }) {
  const map = useMap();
  const fittedKey = useRef('');

  useEffect(() => {
    if (!bounds || bounds.length < 3) return;
    const key = JSON.stringify(bounds);
    if (fittedKey.current === key) return;
    fittedKey.current = key;
    map.fitBounds(bounds as [number, number][], { padding: [48, 48], maxZoom: 16 });
  }, [bounds, map]);

  return null;
}

export function MapDrawHandler({ drawing, points, onAddPoint }: Props) {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    if (drawing) {
      map.dragging.disable();
      map.doubleClickZoom.disable();
      map.boxZoom.disable();
      map.keyboard.disable();
      container.style.cursor = 'crosshair';
    } else {
      map.dragging.enable();
      map.doubleClickZoom.enable();
      map.boxZoom.enable();
      map.keyboard.enable();
      container.style.cursor = '';
    }
    return () => {
      map.dragging.enable();
      map.doubleClickZoom.enable();
      map.boxZoom.enable();
      map.keyboard.enable();
      container.style.cursor = '';
    };
  }, [drawing, map]);

  useMapEvents({
    click(e) {
      if (!drawing) return;
      onAddPoint(e.latlng.lat, e.latlng.lng);
    },
  });

  return (
    <>
      {points.map((p, i) => (
        <CircleMarker
          key={`v-${i}`}
          center={p as [number, number]}
          radius={drawing ? 6 : 4}
          pathOptions={{
            color: drawing ? '#fbbf24' : '#22c55e',
            fillColor: drawing ? '#fbbf24' : '#22c55e',
            fillOpacity: 0.9,
            weight: 2,
          }}
        />
      ))}
      {points.length >= 2 && (
        <Polygon
          positions={points.length >= 3 ? [...points, points[0]] : points}
          pathOptions={{
            color: drawing ? '#fbbf24' : '#22c55e',
            weight: 2,
            fillOpacity: points.length >= 3 ? (drawing ? 0.15 : 0.25) : 0,
          }}
        />
      )}
    </>
  );
}

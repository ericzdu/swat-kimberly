import { useEffect } from 'react';
import { CircleMarker, useMap } from 'react-leaflet';

export interface MapFlyTarget {
  lat: number;
  lng: number;
  zoom?: number;
  label?: string;
}

interface Props {
  target: MapFlyTarget | null;
}

export function MapFlyTo({ target }: Props) {
  const map = useMap();

  useEffect(() => {
    if (!target) return;
    map.flyTo([target.lat, target.lng], target.zoom ?? 14, { duration: 0.8 });
  }, [target, map]);

  if (!target) return null;

  return (
    <CircleMarker
      center={[target.lat, target.lng]}
      radius={10}
      pathOptions={{ color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.85, weight: 2 }}
    />
  );
}

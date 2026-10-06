// Web Mercator fitted to India. The map is drawn from boundaries only, so a projection is
// the whole of the map engine.

export interface Bounds {
  west: number;
  east: number;
  south: number;
  north: number;
}

export const INDIA: Bounds = { west: 68, east: 97.5, south: 6.5, north: 37.5 };
export const NORTH_INDIA: Bounds = { west: 72, east: 81, south: 26, north: 37.1 };

export const REGIONS: [string, Bounds][] = [
  ["India", INDIA],
  ["North", NORTH_INDIA],
  ["West", { west: 68, east: 78.5, south: 15, north: 27 }],
  ["Central", { west: 74, east: 85, south: 17, north: 27 }],
  ["East", { west: 81, east: 97.5, south: 18, north: 29.5 }],
  ["South", { west: 72.5, east: 81, south: 7.5, north: 19 }],
];

// The closest zoom the app offers: about 500 km across, a region around a city. A state,
// never a village: the map cannot be zoomed to the scale at which a field could be found,
// which is the first rule of the app.
export const CLOSEST_KM = 250;

export function around([longitude, latitude]: [number, number], km = CLOSEST_KM): Bounds {
  const dLat = Math.max(km, CLOSEST_KM) / 111.32;
  const dLon = dLat / Math.max(Math.cos((latitude * Math.PI) / 180), 0.2);
  return { west: longitude - dLon, east: longitude + dLon, south: latitude - dLat, north: latitude + dLat };
}

function mercatorY(latitude: number): number {
  const phi = (latitude * Math.PI) / 180;
  return Math.log(Math.tan(Math.PI / 4 + phi / 2));
}

export interface Projection {
  point(longitude: number, latitude: number): [number, number];
  invert(x: number, y: number): [number, number];
  scale: number;
}

export function fit(bounds: Bounds, width: number, height: number, padding = 12): Projection {
  const x0 = (bounds.west * Math.PI) / 180;
  const x1 = (bounds.east * Math.PI) / 180;
  const y0 = mercatorY(bounds.south);
  const y1 = mercatorY(bounds.north);
  const scale = Math.min((width - 2 * padding) / (x1 - x0), (height - 2 * padding) / (y1 - y0));
  const offsetX = (width - scale * (x1 - x0)) / 2;
  const offsetY = (height - scale * (y1 - y0)) / 2;
  return {
    scale,
    point(longitude, latitude) {
      const x = offsetX + scale * ((longitude * Math.PI) / 180 - x0);
      const y = height - (offsetY + scale * (mercatorY(latitude) - y0));
      return [x, y];
    },
    invert(x, y) {
      const longitude = ((x - offsetX) / scale + x0) * (180 / Math.PI);
      const my = (height - y - offsetY) / scale + y0;
      const latitude = (2 * Math.atan(Math.exp(my)) - Math.PI / 2) * (180 / Math.PI);
      return [longitude, latitude];
    },
  };
}

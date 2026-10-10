# -*- coding: utf-8 -*-
"""
Vertical (profile) geometry for LandXML ``ProfAlign`` data.

Builds an evaluatable vertical alignment from the PVI / vertical-curve
elements exported by Civil 3D so an elevation can be obtained at any
station:

* ``PVI``             - grade break (tangent only)
* ``ParaCurve``       - symmetric parabolic vertical curve (``length``)
* ``UnsymParaCurve``  - asymmetric parabolic curve (``length`` + ``length2``)
* ``CircCurve``       - true circular vertical curve (``radius``)

Pure math, no QGIS dependencies.
"""

import math


class VerticalProfile:
    """Vertical alignment defined by PVIs and optional vertical curves."""

    def __init__(self, elements, warnings=None):
        self.warnings = warnings if warnings is not None else []
        self.pvis = [(e['station'], e['elevation']) for e in elements]
        self.curves = []
        if len(self.pvis) >= 2:
            self._build(elements)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_valid(self):
        return len(self.pvis) >= 2

    @property
    def start_station(self):
        return self.pvis[0][0] if self.pvis else None

    @property
    def end_station(self):
        return self.pvis[-1][0] if self.pvis else None

    def elevation_at(self, station):
        """Elevation at a station, or ``None`` outside the profile extent."""
        if not self.is_valid:
            return None
        if station < self.start_station - 1e-6 or station > self.end_station + 1e-6:
            return None

        for curve in self.curves:
            if curve['start'] - 1e-9 <= station <= curve['end'] + 1e-9:
                return self._curve_elevation(curve, station)

        for i in range(1, len(self.pvis)):
            s0, e0 = self.pvis[i - 1]
            s1, e1 = self.pvis[i]
            if station <= s1 + 1e-9:
                span = s1 - s0
                if span <= 0:
                    return e1
                return e0 + (e1 - e0) * (station - s0) / span
        return self.pvis[-1][1]

    def critical_stations(self, tolerance=0.005):
        """PVI stations plus densified vertical curve stations."""
        if not self.is_valid:
            return []

        stations = {round(s, 6) for s, _e in self.pvis}
        for curve in self.curves:
            # The PVI itself is not on the curve; its tangent station is replaced
            stations.discard(round(curve['pvi_station'], 6))
            for station in self._curve_stations(curve, tolerance):
                stations.add(round(station, 6))
        return sorted(stations)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self, elements):
        for i, element in enumerate(elements):
            kind = element['type']
            if kind == 'PVI' or i == 0 or i == len(elements) - 1:
                continue

            g1 = self._grade(i - 1, i)
            g2 = self._grade(i, i + 1)
            if g1 is None or g2 is None:
                continue

            station = element['station']
            elevation = element['elevation']
            length = element.get('length')
            length2 = element.get('length2')
            radius = element.get('radius')

            curve = None
            if kind == 'CircCurve' and radius:
                curve = self._build_circular(station, elevation, g1, g2, radius)
                if curve is None and length:
                    self.warnings.append(
                        "Circular vertical curve at station {0:.3f} had no grade "
                        "change; treated as a tangent.".format(station))
            elif kind == 'UnsymParaCurve' and length and length2:
                curve = self._build_unsym(station, elevation, g1, g2, length, length2)
            elif length:
                curve = self._build_parabola(station, elevation, g1, g2, length)

            if curve is not None:
                curve['pvi_station'] = station
                self.curves.append(curve)

        self.curves.sort(key=lambda c: c['start'])

    def _grade(self, i, j):
        s0, e0 = self.pvis[i]
        s1, e1 = self.pvis[j]
        span = s1 - s0
        if abs(span) < 1e-9:
            return None
        return (e1 - e0) / span

    @staticmethod
    def _build_parabola(station, elevation, g1, g2, length):
        half = length / 2.0
        return {
            'kind': 'para',
            'start': station - half,
            'end': station + half,
            'start_elev': elevation - g1 * half,
            'g1': g1,
            'A': g2 - g1,
            'length': length,
        }

    @staticmethod
    def _build_unsym(station, elevation, g1, g2, length1, length2):
        return {
            'kind': 'unsym',
            'start': station - length1,
            'end': station + length2,
            'start_elev': elevation - g1 * length1,
            'end_elev': elevation + g2 * length2,
            'g1': g1,
            'g2': g2,
            'A': g2 - g1,
            'l1': length1,
            'l2': length2,
        }

    @staticmethod
    def _build_circular(station, elevation, g1, g2, radius):
        theta1 = math.atan(g1)
        theta2 = math.atan(g2)
        delta = theta2 - theta1
        if abs(delta) < 1e-12:
            return None

        tangent = radius * math.tan(abs(delta) / 2.0)
        sign = 1.0 if delta > 0 else -1.0
        # Tangent length is a slope distance; project it onto the station axis
        bvc_station = station - tangent * math.cos(theta1)
        bvc_elev = elevation - tangent * math.sin(theta1)
        # Curve centre sits on the normal to the incoming tangent
        cx = bvc_station - math.sin(theta1) * radius * sign
        cy = bvc_elev + math.cos(theta1) * radius * sign
        return {
            'kind': 'circ',
            'start': bvc_station,
            'end': station + tangent * math.cos(theta2),
            'cx': cx,
            'cy': cy,
            'radius': radius,
            'sign': sign,
        }

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    @staticmethod
    def _curve_elevation(curve, station):
        if curve['kind'] == 'para':
            x = station - curve['start']
            return (curve['start_elev'] + curve['g1'] * x +
                    curve['A'] * x * x / (2.0 * curve['length']))

        if curve['kind'] == 'unsym':
            l1, l2 = curve['l1'], curve['l2']
            total = l1 + l2
            x = station - curve['start']
            if x <= l1:
                return (curve['start_elev'] + curve['g1'] * x +
                        curve['A'] * l2 * x * x / (2.0 * l1 * total))
            x2 = curve['end'] - station
            return (curve['end_elev'] - curve['g2'] * x2 +
                    curve['A'] * l1 * x2 * x2 / (2.0 * l2 * total))

        # circular
        dx = station - curve['cx']
        inner = curve['radius'] ** 2 - dx * dx
        if inner < 0:
            inner = 0.0
        return curve['cy'] - curve['sign'] * math.sqrt(inner)

    @staticmethod
    def _curve_stations(curve, tolerance):
        """Stations along a vertical curve honouring a mid-ordinate tolerance."""
        span = curve['end'] - curve['start']
        if span <= 0:
            return [curve['start']]

        tolerance = max(float(tolerance or 0.005), 1e-6)
        if curve['kind'] == 'circ':
            step = math.sqrt(8.0 * tolerance * curve['radius'])
        else:
            length = curve.get('length') or (curve['l1'] + curve['l2'])
            curvature = abs(curve['A']) / length if length else 0.0
            step = span if curvature <= 1e-12 else math.sqrt(8.0 * tolerance / curvature)

        segments = max(int(math.ceil(span / max(step, 1e-6))), 2)
        segments = min(segments, 500)
        return [curve['start'] + span * i / segments for i in range(segments + 1)]

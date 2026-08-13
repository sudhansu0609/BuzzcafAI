import React, { useRef } from 'react';
import { FaceLandmarks } from '../types/agent';

interface FaceMarkerEditorProps {
  photoUrl: string;
  landmarks: FaceLandmarks;
  onChange: (lm: FaceLandmarks) => void;
  width?: number;
}

const DOT_META: Array<{ key: 'leftEye' | 'rightEye' | 'mouth'; label: string; color: string }> = [
  { key: 'leftEye', label: 'L eye', color: '#38bdf8' },
  { key: 'rightEye', label: 'R eye', color: '#38bdf8' },
  { key: 'mouth', label: 'Mouth', color: '#f472b6' },
];

/**
 * Drag the eye/mouth markers onto the face so the photo animator knows where
 * to blink and open the jaw. Coordinates are stored normalized (0..1 of the
 * image), so they hold up at any render size.
 */
const FaceMarkerEditor: React.FC<FaceMarkerEditorProps> = ({ photoUrl, landmarks, onChange, width = 240 }) => {
  const boxRef = useRef<HTMLDivElement>(null);
  const dragKeyRef = useRef<'leftEye' | 'rightEye' | 'mouth' | null>(null);

  const moveTo = (clientX: number, clientY: number) => {
    const key = dragKeyRef.current;
    const box = boxRef.current;
    if (!key || !box) return;
    const r = box.getBoundingClientRect();
    const x = Math.max(0.02, Math.min(0.98, (clientX - r.left) / r.width));
    const y = Math.max(0.02, Math.min(0.98, (clientY - r.top) / r.height));
    onChange({ ...landmarks, [key]: { x, y } });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div
        ref={boxRef}
        style={{ position: 'relative', width: `${width}px`, userSelect: 'none', touchAction: 'none', borderRadius: '10px', overflow: 'hidden', border: '1px solid #cbd5e1' }}
        onPointerMove={(e) => dragKeyRef.current && moveTo(e.clientX, e.clientY)}
        onPointerUp={() => { dragKeyRef.current = null; }}
        onPointerLeave={() => { dragKeyRef.current = null; }}
      >
        <img src={photoUrl} alt="Face calibration" style={{ width: '100%', display: 'block', pointerEvents: 'none' }} />
        {/* Mouth width guide */}
        <div style={{
          position: 'absolute',
          left: `${(landmarks.mouth.x - landmarks.mouthWidth / 2) * 100}%`,
          top: `${landmarks.mouth.y * 100}%`,
          width: `${landmarks.mouthWidth * 100}%`,
          height: '0',
          borderTop: '2px dashed rgba(244, 114, 182, 0.85)',
          pointerEvents: 'none',
        }} />
        {DOT_META.map(({ key, label, color }) => (
          <div
            key={key}
            onPointerDown={(e) => { dragKeyRef.current = key; (e.target as HTMLElement).setPointerCapture(e.pointerId); moveTo(e.clientX, e.clientY); }}
            title={`Drag onto the ${label.toLowerCase()}`}
            style={{
              position: 'absolute',
              left: `${landmarks[key].x * 100}%`,
              top: `${landmarks[key].y * 100}%`,
              transform: 'translate(-50%, -50%)',
              width: '16px', height: '16px', borderRadius: '50%',
              background: 'rgba(255,255,255,0.25)', border: `2.5px solid ${color}`,
              cursor: 'grab', boxShadow: '0 0 6px rgba(0,0,0,0.6)',
            }}
          />
        ))}
      </div>
      <label style={{ fontSize: '11px', color: '#475569', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
        Mouth width
        <input
          type="range" min={0.08} max={0.42} step={0.01}
          value={landmarks.mouthWidth}
          onChange={(e) => onChange({ ...landmarks, mouthWidth: parseFloat(e.target.value) })}
          style={{ flex: 1 }}
        />
      </label>
      <div style={{ fontSize: '10px', color: '#64748b' }}>
        Drag the dots onto the eyes and mouth center; set the dashed line to the lip width.
      </div>
    </div>
  );
};

export default FaceMarkerEditor;

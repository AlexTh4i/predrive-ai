export type ParrotMood = 'peek' | 'warn' | 'alarm';

interface ParrotMascotProps {
  mood: ParrotMood;
  className?: string;
}

const OUTLINE = '#064E2B';

/**
 * Chú vẹt xanh vẽ tay SVG phong cách Grab:
 * - 'peek': Đậu núp mép phải, mắt chớp tự nhiên
 * - 'warn': Thò đầu ra nhắc nhở, mắt lim dim nhíu mày
 * - 'alarm': Thò đầu nhẹ như lúc lim dim, mắt mở to viền đỏ + rung chuông
 */
export function ParrotMascot({ mood, className = '' }: ParrotMascotProps) {
  const isAlarm = mood === 'alarm';
  const isWarn = mood === 'warn';

  return (
    <svg
      viewBox="0 0 180 180"
      className={`w-full h-full overflow-visible ${isAlarm ? 'bell-shake' : ''} ${className}`}
      aria-hidden="true"
    >
      {/* Đuôi dài rủ xuống */}
      <g stroke={OUTLINE} strokeWidth="2.5" strokeLinejoin="round">
        <path
          d="M 124 150 Q 154 166 156 184 L 132 184 Q 118 170 114 150 Z"
          fill="#0A8F9E"
        />
        <path
          d="M 108 152 Q 130 170 128 184 L 108 184 Q 98 170 96 152 Z"
          fill="#00B14F"
        />
      </g>

      {/* Thân */}
      <path
        d="M 80 98 Q 152 80 160 140 Q 152 178 108 174 Q 72 166 72 130 Q 70 110 80 98 Z"
        fill="#00B14F"
        stroke={OUTLINE}
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <path
        d="M 80 112 Q 100 108 108 130 Q 108 156 90 160 Q 76 152 76 130 Q 76 118 80 112 Z"
        fill="#B8F0CE"
      />

      {/* Cánh gập */}
      <path
        d="M 112 104 Q 154 108 152 150 Q 150 170 130 174 Q 112 150 112 104 Z"
        fill="#00804A"
        stroke={OUTLINE}
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path
        d="M 124 124 Q 136 142 132 162 M 136 120 Q 146 138 144 156"
        stroke="#0A8F9E"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />

      {/* Chân bám */}
      <g fill="#F5A623" stroke={OUTLINE} strokeWidth="2">
        <ellipse cx="96" cy="174" rx="10" ry="4.5" />
        <ellipse cx="114" cy="176" rx="10" ry="4.5" />
      </g>

      {/* Đầu */}
      <circle cx="90" cy="72" r="38" fill="#00B14F" stroke={OUTLINE} strokeWidth="3" />

      {/* Chỏm lông vuốt ra sau */}
      <g className="comb-anim">
        <path
          d="M 98 36 Q 102 14 116 10 Q 110 24 118 30 Q 126 18 138 20 Q 126 30 126 44 Z"
          fill="#00804A"
          stroke={OUTLINE}
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
        <path
          d="M 116 10 Q 120 8 122 12 M 138 20 Q 142 22 140 26"
          stroke="#E5372B"
          strokeWidth="3.5"
          fill="none"
          strokeLinecap="round"
        />
      </g>

      {/* Mảng đỏ trên trán */}
      <path d="M 66 48 Q 80 36 98 38 Q 86 50 70 56 Z" fill="#E5372B" />

      {/* Mảng trắng quanh mắt */}
      <ellipse
        cx="78"
        cy="74"
        rx="17"
        ry="15"
        fill="#FFFFFF"
        stroke={OUTLINE}
        strokeWidth="2.5"
      />

      {isAlarm ? (
        <>
          <circle cx="76" cy="74" r="10" fill="#E5372B" />
          <circle cx="76" cy="74" r="4" fill="#1C1C1C" />
          <circle cx="73" cy="71" r="2" fill="#FFFFFF" />
          <line
            x1="60"
            y1="54"
            x2="92"
            y2="60"
            stroke={OUTLINE}
            strokeWidth="4.5"
            strokeLinecap="round"
          />
        </>
      ) : isWarn ? (
        <>
          <circle cx="76" cy="78" r="5.5" fill="#1C1C1C" />
          <path
            d="M 61 74 A 17 15 0 0 1 95 74 Z"
            fill="#00B14F"
            stroke={OUTLINE}
            strokeWidth="2.5"
            strokeLinejoin="round"
          />
          <line
            x1="60"
            y1="56"
            x2="92"
            y2="62"
            stroke={OUTLINE}
            strokeWidth="4.5"
            strokeLinecap="round"
          />
        </>
      ) : (
        <g className="eye-blink">
          <circle cx="75" cy="74" r="7" fill="#1C1C1C" />
          <circle cx="73" cy="71" r="2.6" fill="#FFFFFF" />
        </g>
      )}

      {/* Mỏ trên khoằm to */}
      <path
        d="M 64 56 C 30 50 22 84 40 104 C 48 112 60 108 62 98 C 54 90 60 76 70 70 Z"
        fill="#F5A623"
        stroke={OUTLINE}
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <circle cx="56" cy="66" r="2.2" fill={OUTLINE} />
      <path
        d="M 46 96 Q 52 102 60 98"
        stroke={OUTLINE}
        strokeWidth="1.8"
        fill="none"
        strokeLinecap="round"
      />

      {/* Mỏ dưới */}
      <path
        d="M 54 100 Q 58 118 80 110 Q 70 102 62 100 Z"
        fill="#E08A10"
        stroke={OUTLINE}
        strokeWidth="2.2"
        strokeLinejoin="round"
      />

      {isAlarm && (
        <>
          <g stroke="#FFFFFF" strokeWidth="4" fill="none" strokeLinecap="round">
            <path className="wave" d="M 18 70 Q 10 82 18 94" />
            <path className="wave wave-2" d="M 6 64 Q -6 82 6 100" />
          </g>
          <path d="M 112 34 Q 108 44 116 46 Q 122 44 112 34" fill="#38BDF8" />
        </>
      )}
    </svg>
  );
}


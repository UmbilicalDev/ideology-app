import { useCallback, useEffect, useRef, useState, type CSSProperties, type TouchEvent } from "react";

import answerDarkPoster from "../../assets/how-it-works/answer-dark.webp";
import answerDarkVideo from "../../assets/how-it-works/answer-dark.mp4";
import answerLightPoster from "../../assets/how-it-works/answer-light.webp";
import answerLightVideo from "../../assets/how-it-works/answer-light.mp4";
import evidenceDarkPoster from "../../assets/how-it-works/evidence-dark.webp";
import evidenceDarkVideo from "../../assets/how-it-works/evidence-dark.mp4";
import evidenceLightPoster from "../../assets/how-it-works/evidence-light.webp";
import evidenceLightVideo from "../../assets/how-it-works/evidence-light.mp4";
import resultsDarkPoster from "../../assets/how-it-works/results-dark.webp";
import resultsDarkVideo from "../../assets/how-it-works/results-dark.mp4";
import resultsLightPoster from "../../assets/how-it-works/results-light.webp";
import resultsLightVideo from "../../assets/how-it-works/results-light.mp4";
import { CheckIcon, ChevronLeftIcon, ChevronRightIcon, PauseIcon, PlayIcon } from "../../ui/icons";
import { useMediaQuery } from "../common/useMediaQuery";

interface Media {
  readonly video: string;
  readonly poster: string;
}

export interface HowItWorksSlide {
  readonly title: string;
  readonly points: readonly string[];
  readonly dark: Media;
  readonly light: Media;
}

export const HOW_IT_WORKS_SLIDES: readonly HowItWorksSlide[] = [
  {
    title: "Responde a las afirmaciones",
    points: [
      "Elige tu grado de acuerdo.",
      "Puedes saltarte las que quieras.",
      "Marca como importantes las que más te importan.",
    ],
    dark: { video: answerDarkVideo, poster: answerDarkPoster },
    light: { video: answerLightVideo, poster: answerLightPoster },
  },
  {
    title: "Revisa tus resultados",
    points: [
      "Comprueba en qué porcentaje coincides con cada partido.",
      "Comparte tu resultado con quien quieras.",
    ],
    dark: { video: resultsDarkVideo, poster: resultsDarkPoster },
    light: { video: resultsLightVideo, poster: resultsLightPoster },
  },
  {
    title: "Comprueba de dónde vienen los resultados",
    points: [
      "Revisa qué dice exactamente cada partido sobre cada afirmación.",
      "Accede mediante enlace a las citas en los programas electorales.",
    ],
    dark: { video: evidenceDarkVideo, poster: evidenceDarkPoster },
    light: { video: evidenceLightVideo, poster: evidenceLightPoster },
  },
];

/** Used when a recording cannot play (autoplay blocked, load error). */
export const FALLBACK_SLIDE_MS = 9000;
const SWIPE_MIN_PX = 40;

type Direction = "forward" | "back";

function focusVisible(element: Element): boolean {
  try {
    return element.matches(":focus-visible");
  } catch {
    // Engines without :focus-visible (jsdom): treat any focus as keyboard focus.
    return true;
  }
}

/**
 * Landing `Cómo funciona` carousel (DESIGN.md "How-it-works carousel"): three
 * pages, each a short text and a screen recording of the app, in an endless
 * loop. A page advances when its recording ends; pointer hover, keyboard focus
 * inside, the pause button or being off screen hold it. Under reduced motion it
 * starts paused, showing each recording's first frame. The recordings are
 * decorative: the text says everything they show.
 */
export function HowItWorksCarousel({
  slides = HOW_IT_WORKS_SLIDES,
}: {
  readonly slides?: readonly HowItWorksSlide[];
}) {
  const count = slides.length;
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const light = useMediaQuery("(prefers-color-scheme: light)");
  const [active, setActive] = useState(0);
  const [direction, setDirection] = useState<Direction | null>(null);
  const [userPaused, setUserPaused] = useState<boolean | null>(null);
  const [held, setHeld] = useState(false);
  const [inView, setInView] = useState(true);
  const [progress, setProgress] = useState(0);
  const rootRef = useRef<HTMLElement>(null);
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([]);
  const touchStartX = useRef<number | null>(null);

  // Until the Voter picks, reduced motion means paused.
  const paused = userPaused ?? reducedMotion;
  const playing = !paused && inView;
  const advancing = playing && !held;

  const go = useCallback(
    (index: number, dir: Direction) => {
      setDirection(dir);
      setProgress(0);
      setActive(((index % count) + count) % count);
    },
    [count],
  );
  const next = useCallback(() => go(active + 1, "forward"), [active, go]);
  const previous = useCallback(() => go(active - 1, "back"), [active, go]);

  // Only play while the carousel is on screen.
  useEffect(() => {
    const element = rootRef.current;
    if (element === null || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry?.isIntersecting ?? true), {
      threshold: 0.25,
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Play the active recording from the start; stop the others.
  useEffect(() => {
    videoRefs.current.forEach((video, index) => {
      if (video !== null && index !== active) {
        video.pause();
        video.currentTime = 0;
      }
    });
  }, [active]);

  const [stalled, setStalled] = useState(false);
  useEffect(() => {
    const video = videoRefs.current[active];
    setStalled(false);
    if (video === null || video === undefined) return;
    if (!playing) {
      video.pause();
      return;
    }
    let result: Promise<void> | undefined;
    try {
      result = video.play() as Promise<void> | undefined;
    } catch {
      setStalled(true);
      return;
    }
    result?.catch(() => setStalled(true));
  }, [active, playing, light]);

  // A recording that cannot play still lets the carousel move on.
  useEffect(() => {
    if (!stalled || !advancing) return;
    const timer = window.setTimeout(next, FALLBACK_SLIDE_MS);
    return () => window.clearTimeout(timer);
  }, [stalled, advancing, next]);

  const onEnded = (index: number) => {
    if (index !== active) return;
    if (advancing) {
      next();
      return;
    }
    // Held (hover, focus): replay the same page instead of moving on.
    const video = videoRefs.current[index];
    if (video && playing) {
      video.currentTime = 0;
      void video.play()?.catch?.(() => setStalled(true));
    }
  };

  const onTimeUpdate = (index: number) => {
    const video = videoRefs.current[index];
    if (index !== active || !video || !Number.isFinite(video.duration) || video.duration <= 0) return;
    setProgress(Math.min(1, video.currentTime / video.duration));
  };

  const onTouchStart = (event: TouchEvent) => {
    touchStartX.current = event.touches[0]?.clientX ?? null;
  };
  const onTouchEnd = (event: TouchEvent) => {
    const start = touchStartX.current;
    touchStartX.current = null;
    const end = event.changedTouches[0]?.clientX;
    if (start === null || end === undefined) return;
    const delta = end - start;
    if (Math.abs(delta) < SWIPE_MIN_PX) return;
    if (delta < 0) next();
    else previous();
  };

  return (
    <section
      ref={rootRef}
      className="how-it-works"
      aria-roledescription="carrusel"
      aria-label="Cómo funciona"
      data-playing={advancing ? "true" : "false"}
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse") setHeld(true);
      }}
      onPointerLeave={(event) => {
        if (event.pointerType === "mouse") setHeld(false);
      }}
      // Keyboard focus holds the page (a mouse click on an arrow does not,
      // so the rotation picks up again once the pointer leaves).
      onFocus={(event) => {
        if (focusVisible(event.target)) setHeld(true);
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setHeld(false);
      }}
    >
      <div
        className="how-it-works__slides"
        aria-live={advancing ? "off" : "polite"}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
      >
        {slides.map((slide, index) => {
          const current = index === active;
          const media = light ? slide.light : slide.dark;
          return (
            <div
              key={slide.title}
              className="how-slide"
              role="group"
              aria-roledescription="diapositiva"
              aria-label={`${index + 1} de ${count}`}
              aria-hidden={current ? undefined : true}
              inert={!current}
              data-active={current ? "true" : "false"}
              data-direction={current && direction !== null ? direction : undefined}
            >
              <div className="how-slide__text">
                <p className="how-slide__step">{`Paso ${index + 1} de ${count}`}</p>
                <h2 className="how-slide__title">{slide.title}</h2>
                <ul className="how-slide__points">
                  {slide.points.map((point) => (
                    <li key={point}>
                      <CheckIcon />
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="how-slide__media">
                <video
                  ref={(element) => {
                    videoRefs.current[index] = element;
                  }}
                  key={media.video}
                  className="how-slide__video"
                  src={media.video}
                  poster={media.poster}
                  muted
                  playsInline
                  preload={current ? "auto" : "none"}
                  disablePictureInPicture
                  aria-hidden="true"
                  tabIndex={-1}
                  width={960}
                  height={640}
                  onEnded={() => onEnded(index)}
                  onTimeUpdate={() => onTimeUpdate(index)}
                  onError={() => {
                    if (index === active) setStalled(true);
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <button
        type="button"
        className="how-it-works__arrow how-it-works__arrow--prev"
        aria-label="Página anterior"
        onClick={previous}
      >
        <ChevronLeftIcon />
      </button>
      <button
        type="button"
        className="how-it-works__arrow how-it-works__arrow--next"
        aria-label="Página siguiente"
        onClick={next}
      >
        <ChevronRightIcon />
      </button>

      <div className="how-it-works__controls">
        <button
          type="button"
          className="how-it-works__pause"
          aria-label={paused ? "Reanudar el carrusel" : "Pausar el carrusel"}
          onClick={() => setUserPaused(!paused)}
        >
          {paused ? <PlayIcon /> : <PauseIcon />}
        </button>
        <div className="how-it-works__dots">
          {slides.map((slide, index) => (
            <button
              key={slide.title}
              type="button"
              className="how-it-works__dot"
              aria-label={`Ir a la página ${index + 1}: ${slide.title}`}
              aria-current={index === active ? "true" : undefined}
              style={
                index === active ? ({ "--how-progress": String(progress) } as CSSProperties) : undefined
              }
              onClick={() => {
                if (index !== active) go(index, index > active ? "forward" : "back");
              }}
            >
              <span className="how-it-works__dot-fill" aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

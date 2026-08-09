import { useEffect, useState } from "react";
import { HERO_VIDEO_URL } from "../config/branding";

export function CinematicBackground({ state }) {
  const [ready, setReady] = useState(false);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      if (!ready) {
        console.info("FundTrace hero video timeout; using visual fallback.");
        setFallback(true);
      }
    }, 7000);
    return () => window.clearTimeout(timeout);
  }, [ready]);

  const failVideo = () => {
    console.info("FundTrace hero video unavailable; using visual fallback.");
    setFallback(true);
  };

  return (
    <div className={`cinematic-background ${state}`} aria-hidden="true">
      <div className={`market-fallback ${fallback ? "is-visible" : ""}`}>
        <svg viewBox="0 0 1440 900" preserveAspectRatio="none">
          <path d="M0 670 C120 620 170 720 285 650 S470 500 570 555 S745 685 850 575 S1040 390 1140 455 S1325 565 1440 410" />
          <path d="M0 760 C190 700 290 790 430 710 S690 590 810 650 S1060 760 1220 590 S1370 500 1440 535" />
        </svg>
      </div>
      {!fallback && (
        <video
          className={`hero-video ${ready ? "is-ready" : ""}`}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          onCanPlay={() => setReady(true)}
          onError={failVideo}
        >
          <source src={HERO_VIDEO_URL} type="video/mp4" />
        </video>
      )}
      <div className="bottom-blur-overlay" />
    </div>
  );
}

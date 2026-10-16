"""Write a 60 s MP4 with a big mm:ss clock, so seeking in the report can be checked by eye.

    python scripts/make_demo_video.py demo.mp4        # needs opencv-python (the AI venv has it)

The video contains no face; it only gives the seeded demo timeline something to play.
"""

import sys

import cv2
import numpy as np

SECONDS, FPS, SIZE = 60, 5, (480, 270)


def main(path):
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, SIZE)
    for index in range(SECONDS * FPS):
        second = index // FPS
        frame = np.full((SIZE[1], SIZE[0], 3), (40 + 3 * second, 70, 200 - 3 * second), np.uint8)
        label = f"{second // 60:02d}:{second % 60:02d}"
        cv2.putText(frame, label, (120, 160), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 6)
        writer.write(frame)
    writer.release()
    print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo.mp4")

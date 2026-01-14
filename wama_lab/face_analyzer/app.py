"""
face_analyzer - WAMA Lab Application

Standalone scientific application.
Executed via subprocess from WAMA core.
"""

import argparse


def main():
    parser = argparse.ArgumentParser(description="face_analyzer - WAMA Lab App")
    parser.add_argument("--input", help="Input file (video/image)", required=False)
    parser.add_argument("--output", help="Output folder", required=False)

    args = parser.parse_args()

    print("🚀 face_analyzer launched")
    print(f"Input  : {args.input}")
    print(f"Output : {args.output}")


if __name__ == "__main__":
    main()

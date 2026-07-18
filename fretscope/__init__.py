"""FretScope: guitar tone & tab analyzer.

Isolates the guitar part of a song, transcribes it (tab or chord chart), and
estimates the tone chain that produced it. See README.md for honest limitations.
"""

__version__ = "0.1.0"

# Default analysis sample rate. 22.05 kHz keeps everything a guitar produces
# (fundamentals top out ~1.3 kHz, meaningful harmonics well under 10 kHz) while
# halving compute vs 44.1 kHz.
ANALYSIS_SR = 22050

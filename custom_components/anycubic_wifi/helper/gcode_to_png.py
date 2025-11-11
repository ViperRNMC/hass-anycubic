# G-code naar PNG helper met pygcode en matplotlib
import matplotlib.pyplot as plt
from pygcode import Line


def gcode_to_png(gcode_path, png_path):
    x, y = 0, 0
    xs, ys = [], []
    with open(gcode_path, 'r') as f:
        for line in f:
            try:
                gline = Line(line)
                if gline.block.gcodes:
                    for gcode in gline.block.gcodes:
                        if gcode.word == 'G' and gcode.value in [0, 1]:
                            # Move or draw
                            x_new = gline.block.get_param('X', x)
                            y_new = gline.block.get_param('Y', y)
                            xs.extend([x, x_new])
                            ys.extend([y, y_new])
                            x, y = x_new, y_new
            except Exception:
                continue
    plt.figure(figsize=(6, 6))
    plt.plot(xs, ys, color='black', linewidth=0.5)
    plt.axis('equal')
    plt.axis('off')
    plt.savefig(png_path, bbox_inches='tight', pad_inches=0)
    plt.close()

# Voorbeeld gebruik:
# gcode_to_png('voorbeeld.gcode', 'voorbeeld.png')

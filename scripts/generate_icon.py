from PIL import Image, ImageDraw
import struct
import os

os.makedirs('desktop-shell/assets', exist_ok=True)
img = Image.new('RGBA', (256, 256), (10, 10, 46, 255))
draw = ImageDraw.Draw(img)
draw.ellipse([64, 64, 192, 192], fill=(0, 255, 136, 255))
img.save('desktop-shell/assets/icon.png')
with open('desktop-shell/assets/icon.png', 'rb') as f:
    png_data = f.read()
ico_header = struct.pack('<HHH', 0, 1, 1)
ico_entry = struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(png_data), 22)
with open('desktop-shell/assets/icon.ico', 'wb') as f:
    f.write(ico_header + ico_entry + png_data)
print('Icon generated successfully')

import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

def generate_pitch(output_path, width=1920, height=1080):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    # 1. Base vibrant grass with striped turf pattern (Lighter stadium pitch)
    img = Image.new('RGB', (width, height), '#1b4332')
    draw = ImageDraw.Draw(img)
    
    n_stripes = 14
    stripe_w = width / n_stripes
    for i in range(n_stripes):
        color = '#1f4e3a' if i % 2 == 0 else '#29634b'
        draw.rectangle([i * stripe_w, 0, (i + 1) * stripe_w, height], fill=color)
        
    # 2. Add fine grass texture
    np_img = np.array(img, dtype=np.int16)
    noise = np.random.normal(0, 5, (height, width, 3)).astype(np.int16)
    np_img = np.clip(np_img + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(np_img)
    draw = ImageDraw.Draw(img)
    
    # 3. Draw soccer pitch chalk lines
    pad_x = 90
    pad_y = 55
    field_w = width - 2 * pad_x
    field_h = height - 2 * pad_y
    line_col = '#ffffff'
    line_w = 4
    
    # Outer touchline
    draw.rectangle([pad_x, pad_y, width - pad_x, height - pad_y], outline=line_col, width=line_w)
    
    # Halfway line
    mid_x = width // 2
    draw.line([(mid_x, pad_y), (mid_x, height - pad_y)], fill=line_col, width=line_w)
    
    # Center circle & spot
    r_circle = 150
    draw.ellipse([mid_x - r_circle, height//2 - r_circle, mid_x + r_circle, height//2 + r_circle], outline=line_col, width=line_w)
    draw.ellipse([mid_x - 9, height//2 - 9, mid_x + 9, height//2 + 9], fill=line_col)
    
    # Penalty boxes (Left and Right)
    pen_w = int(field_w * 0.17)
    pen_h = int(field_h * 0.44)
    pen_y1 = height//2 - pen_h//2
    pen_y2 = height//2 + pen_h//2
    
    # Left penalty box & goal area
    draw.rectangle([pad_x, pen_y1, pad_x + pen_w, pen_y2], outline=line_col, width=line_w)
    draw.rectangle([pad_x, height//2 - int(pen_h*0.42)//2, pad_x + int(pen_w*0.35), height//2 + int(pen_h*0.42)//2], outline=line_col, width=line_w)
    draw.ellipse([pad_x + int(pen_w*0.65) - 7, height//2 - 7, pad_x + int(pen_w*0.65) + 7, height//2 + 7], fill=line_col)
    
    # Right penalty box & goal area
    draw.rectangle([width - pad_x - pen_w, pen_y1, width - pad_x, pen_y2], outline=line_col, width=line_w)
    draw.rectangle([width - pad_x - int(pen_w*0.35), height//2 - int(pen_h*0.42)//2, width - pad_x, height//2 + int(pen_h*0.42)//2], outline=line_col, width=line_w)
    draw.ellipse([width - pad_x - int(pen_w*0.65) - 7, height//2 - 7, width - pad_x - int(pen_w*0.65) + 7, height//2 + 7], fill=line_col)
    
    # Corner arcs
    r_cor = 30
    draw.arc([pad_x - r_cor, pad_y - r_cor, pad_x + r_cor, pad_y + r_cor], 0, 90, fill=line_col, width=line_w)
    draw.arc([pad_x - r_cor, height - pad_y - r_cor, pad_x + r_cor, height - pad_y + r_cor], 270, 360, fill=line_col, width=line_w)
    draw.arc([width - pad_x - r_cor, pad_y - r_cor, width - pad_x + r_cor, pad_y + r_cor], 90, 180, fill=line_col, width=line_w)
    draw.arc([width - pad_x - r_cor, height - pad_y - r_cor, width - pad_x + r_cor, height - pad_y + r_cor], 180, 270, fill=line_col, width=line_w)

    # 4. Subtle Vignette (very light so field stays bright)
    vignette = Image.new('L', (width, height), 0)
    v_draw = ImageDraw.Draw(vignette)
    for r in range(max(width, height), 0, -25):
        factor = r / max(width, height)
        alpha = int(140 * (1.0 - factor**1.5))
        v_draw.ellipse([width//2 - r, height//2 - r, width//2 + r, height//2 + r], fill=min(140, alpha))
    vignette = vignette.filter(ImageFilter.GaussianBlur(80))
    
    dark_layer = Image.new('RGB', (width, height), '#0a2115')
    img = Image.composite(img, dark_layer, vignette)
    
    img.save(output_path, quality=95)
    print("Generated light pitch at:", output_path)

if __name__ == '__main__':
    target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'soccer_pitch_bg.jpg')
    generate_pitch(target)

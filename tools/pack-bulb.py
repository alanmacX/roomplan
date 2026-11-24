"""Package the Poly Haven CC0 lightbulb_led glTF + textures for offline preview."""
from array import array
from base64 import b64encode
from io import BytesIO
from pathlib import Path
import json
import sys
from PIL import Image

p=Path(sys.argv[1])
a=json.loads(p.read_text())
raw=(p.parent/a['buffers'][0]['uri']).read_bytes()
def accessor(i):
    prop=a['accessors'][i]; view=a['bufferViews'][prop['bufferView']]
    channels={'SCALAR':1,'VEC2':2,'VEC3':3}[prop['type']]
    kind,width={5123:('H',2),5126:('f',4)}[prop['componentType']]
    step=channels*width
    assert view.get('byteStride',step)==step
    start=view.get('byteOffset',0)+prop.get('byteOffset',0)
    return raw[start:start+prop['count']*step]
def texture(i):
    with Image.open(p.parent/a['images'][i]['uri']) as img:
        img.thumbnail((512,512))
        buf=BytesIO();img.convert('RGB').save(buf,'JPEG',quality=84)
    return 'data:image/jpeg;base64,'+b64encode(buf.getvalue()).decode()
out={name:b64encode(accessor(i)).decode() for i,name in enumerate(['position','normal','uv','index'])}
out['textures']=[texture(i) for i in range(3)]
positions=array('f');positions.frombytes(accessor(0))
indices=array('H');indices.frombytes(accessor(3))
print('ranges along y by largest radius:')
for y in range(-1,9):
    pts=[(x*x+z*z)**0.5 for x,t,z in zip(positions[::3],positions[1::3],positions[2::3]) if y/100<=t<(y+1)/100]
    print(y, round(max(pts),3) if pts else '-')
print('Triangles:',len(indices)//3)
Path(sys.argv[2]).write_text('window.LED_BULB_ASSET = '+json.dumps(out,separators=(',',':'))+';\n')

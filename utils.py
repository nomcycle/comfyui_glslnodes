import requests
import re

from .texture import ImageTexture, ImageArrayTexture

import numpy as np

GL_BACKENDS = {
    "Linux": "egl",
    "Darwin": "cgl",
}

GL_PLATFORMS = {
    "Linux": "PLATFORM_LINUX",
    "Darwin": "PLATFORM_OSX",
    "Windows": "PLATFORM_WIN",
}

GLSL_VERSIONS = ["100", "120", "130", "140", "150", "330", "330 core", "400", "410", "420", "430", "440"]

GLSL_FRAGMENT_HEADER = """
#if __VERSION__ >= 130
out vec4 fragColor;
#define gl_FragColor fragColor
#define texture2D(TEX, UV) texture(TEX, UV)
#else
#extension GL_EXT_texture_array : enable
#endif
#ifdef GL_ES
precision mediump float;
#endif
#line 1
"""

DEFAULT_FRAGMENT_SHADER= """
// <NAME>_TYPE: have the uniform type
//uniform U_TEX0_TYPE u_tex0;
//uniform U_TEX0_TYPE u_val0;

uniform vec4    u_date;
uniform vec2    u_resolution;
uniform float   u_delta;
uniform float   u_time;
uniform float   u_fps;
uniform int     u_frame;

void main() {
    vec4 color = vec4(0.0, 0.0, 0.0, 1.0);
    vec2 pixel = 1.0 / u_resolution;
    vec2 st = gl_FragCoord.xy * pixel;

    color.rgb = vec3(st, 0.5 + 0.5 * cos(u_time));

    // texture arrays have this <NAME>_TOTALFRAMES
    //#ifdef U_TEX0_TOTALFRAMES
    //color = texture(u_tex0, vec3(st, float(u_frame)));
    //#else
    //color = texture(u_tex0, st);
    //#endif

    gl_FragColor = color;
}
"""

GLSL_SHADERTOY_HEADER = """
out vec4 fragColor;

#ifdef U_TEX0_TYPE
uniform U_TEX0_TYPE u_tex0;
#define iChannel0 u_tex0
#endif

#ifdef U_TEX1_TYPE
uniform U_TEX1_TYPE u_tex1;
#define iChannel1 u_tex1
#endif

#ifdef U_TEX2_TYPE
uniform U_TEX2_TYPE u_tex1;
#define iChannel2 u_tex2
#endif

#ifdef U_TEX3_TYPE
uniform U_TEX3_TYPE u_tex1;
#define iChannel3 u_tex3
#endif

uniform vec4    u_date;
#define iDate   u_date

uniform vec2    u_resolution;
#define iResolution u_resolution

#define iMouse  vec2(0.0)

uniform float   u_time;
#define iTime   u_time

uniform float   u_delta;
#define iTimeDelta u_delta

uniform float   u_fps;

uniform int     u_frame;
#define iFrame  u_frame

void mainImage( out vec4 fragColor, in vec2 fragCoord );

void main() {
    vec4 color = vec4(0.0, 0.0, 0.0, 1.0);
    vec2 st = gl_FragCoord.xy;
    mainImage(color, st);
    fragColor = color;
}
"""

DEFAULT_SHADERTOY_SHADER = """void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    // Normalized pixel coordinates (from 0 to 1)
    vec2 uv = fragCoord/iResolution.xy;

    // Time varying pixel color
    vec3 col = 0.5 + 0.5*cos(iTime+uv.xyx+vec3(0,2,4));

    // Output to screen
    fragColor = vec4(col,1.0);
}
"""

BILLBOARD_GEOM = np.array([
    # First triangle
    -1.0, -1.0, 
    -1.0,  1.0,
        1.0,  1.0,
    # Second triangle
    -1.0, -1.0,
        1.0,  1.0,
        1.0, -1.0,
], dtype='f4')


def resolveLygia(src: str):
    source = ""
    lines = src.split("\n")
    for line in lines:
        # resolve #include dependencies
        match = re.search(r'#include\s*["|<](.*.glsl)["|>]', line, re.IGNORECASE)
        if match:
            url = match.group(1)
            print("Adding dependecy", url)
            if url.startswith("lygia"):
                url = url.replace("lygia", "https://lygia.xyz")

                response = requests.get(url, headers={
                    "Origin": "ComfyUI Server",
                })
                if response.status_code == 200:
                    source += response.text + "\n"
                else:
                    print("Failed to fetch", url)

        else:
            source += line + "\n"

    return source


def getBillboard(ctx, program):
    vbo = ctx.buffer(BILLBOARD_GEOM)
    return ctx.simple_vertex_array(program, vbo, 'a_position')


def getDefaultVertexShader(version):
    out = "#version " + version + "\n"
    if version == "100" or version == "120":
        out += """
#ifdef GL_ES
precision highp float;
#endif

attribute vec2 a_position;
varying vec2 v_texcoord;
"""
    else:
        out += """
in vec2 a_position;
out vec2 v_texcoord;
"""

    out += """
void main() {
    v_texcoord = a_position * 0.5 + 0.5;
    gl_Position = vec4(a_position, 0.0, 1.0);
}
"""
    return out


def getFragmentShader(fragment_code, defines):
    out = "#version " + fragment_code["version"] + "\n" 

    # Stack defines
    for define in defines:
        out += f"#define {define[0]} {define[1]}\n"

    if fragment_code["specs"] == "shadertoy":
        print("Using Shadertoy Header")
        out += GLSL_SHADERTOY_HEADER
    else:
        out += GLSL_FRAGMENT_HEADER 

    out += "\n#line 1\n" 
    out += fragment_code["src"]
    return out


def setProgram(ctx, defines, fragment_code, vertex_code=None, geometry=None):
    return ctx.program( vertex_shader= getDefaultVertexShader(fragment_code["version"]),
                        fragment_shader= getFragmentShader(fragment_code, defines) )


def loadTextures(images, uniforms, defines):
    textures = []
    for key, value in images.items():
        if value is not None:
            if len(value) is 1:
                tex = ImageTexture(value.numpy()[0], key)
                textures.append( tex )
                uniforms[f"{key}Resolution"] = (float(tex.width), float(tex.height))
                defines.append((f"{key.upper()}_TYPE", "sampler2D"))
            else:
                tex = ImageArrayTexture(value.numpy(), key)
                textures.append( tex )
                uniforms[f"{key}Resolution"] = (float(tex.width), float(tex.height))
                uniforms[f"{key}TotalFrames"] = float(tex.totalFrames)
                defines.append((f"{key.upper()}_TOTALFRAMES", float(tex.totalFrames)))
                defines.append((f"{key.upper()}_TYPE", "sampler2DArray"))
    return textures


def useTextures(program, textures):
    for i, texture in enumerate(textures):
        texture.use(i, program)
    return textures


def loadUniforms(values, uniforms, defines):
    for key, value in values.items():
        if value is not None:
            if type(value) is int or type(value) is float:
                uniforms[key] = value
                defines.append((f"{key.upper()}_TYPE", "float"))
            elif type(value) is list or type(value) is tuple:
                uniforms[key] = value
                defines.append((f"{key.upper()}_TYPE", "vec" + str(len(value))))
    return uniforms


def useUniforms(program, uniforms):
    for key, value in uniforms.items():
        if key in program:
            if value is not None:
                program[key] = value



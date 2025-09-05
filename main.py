# main.py
from fastapi import FastAPI, File, UploadFile, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import base64
import openai

app = FastAPI()

# Permitir conexiones desde cualquier origen (para pruebas y uso con Softr)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Licencias válidas (puedes expandir esto a una base de datos si quieres)
LICENSES = {"LICENCIA123": "cliente1", "LICENCIA456": "cliente2"}

def analizar_pdf_y_extraer_ficha(file_bytes, openai_api_key):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    is_digital = True
    digital_texts = []
    for page in doc:
        page_text = page.get_text("text")
        digital_texts.append(page_text)
        if len(page_text.strip()) < 30:
            is_digital = False

    all_texts = []
    client = openai.OpenAI(api_key=openai_api_key)

    if is_digital:
        for page_text in digital_texts:
            all_texts.append(page_text)
    else:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
            messages = [
                {"role": "system", "content": "Eres un experto en contratos públicos y OCR legal."},
                {"role": "user", "content": [
                    {"type": "text", "text": (
                        "Lee la imagen adjunta de un contrato, extrae todo el texto útil y, si detectas información de partes, objeto, monto, plazo, garantías, "
                        "obligaciones, penalizaciones, modificaciones, normatividad aplicable, resolución de controversias, firmas o anexos, indícalo claramente. "
                        "No agregues explicaciones, solo texto estructurado."
                    )},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
                ]}
            ]
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=2048,
            )
            page_text = response.choices[0].message.content
            all_texts.append(page_text)

    full_text = "\n\n".join(all_texts)

    prompt_final = (
        "Eres un analista legal experto en contratos públicos. Recibiste el texto extraído de un contrato de la administración pública mexicana. "
        "DEBES LLENAR CADA CAMPO DE LA SIGUIENTE TABLA (presenta solo la tabla, formato markdown, nada más) con la información literal del texto, sin explicar, resumir, interpretar, fusionar, ni reorganizar datos. "
        "NO inventes, NO omitas, NO combines, NO uses frases generales. Si no encuentras el dato, escribe 'NO LOCALIZADO' exactamente así, sin adornos. "
        "NO repitas el texto del contrato ni des contexto fuera de la tabla. NO elimines ningún campo aunque esté vacío. "
        "SIEMPRE utiliza el mismo orden y formato."
        "\n\n"
        "| Campo                       | Respuesta                                                         |\n"
        "|-----------------------------|--------------------------------------------------------------------|\n"
        "| Partes                      | Por la Secretaría: [Nombres y cargos literales]. Por el Proveedor: [Nombres, cargos, razón social literal]. |\n"
        "| Objeto                      | [Todos los servicios, bienes u obras, uno por renglón literal].    |\n"
        "| Monto antes de IVA          | $[####,###.##] MXN (literal).                                      |\n"
        "| IVA                         | $[####,###.##] MXN (literal).                                      |\n"
        "| Monto total                 | $[####,###.##] MXN (literal).                                      |\n"
        "| Fecha de inicio             | [Fecha literal].                                                   |\n"
        "| Fecha de fin                | [Fecha literal].                                                   |\n"
        "| Vigencia/Plazo              | [Literal].                                                        |\n"
        "| Garantía(s)                 | [Tipo, porcentaje y condiciones de cada garantía, literal].        |\n"
        "| Obligaciones proveedor      | [Cada obligación textual, en renglón aparte].                     |\n"
        "| Supervisión                 | [Cargo(s), nombre(s) responsable(s) textual(es)].                  |\n"
        "| Penalizaciones              | [Cada penalización, monto y condición, renglón aparte, literal].   |\n"
        "| Penalización máxima         | [Literal].                                                        |\n"
        "| Modificaciones              | [Procedimiento, máximo permitido, fundamento legal, renglón aparte, literal]. |\n"
        "| Normatividad aplicable      | [Cada ley, reglamento, NOM o código textual, renglón aparte].      |\n"
        "| Resolución de controversias | [Literal. Si no hay procedimiento, inicia con 'NO LOCALIZADO.'].   |\n"
        "| Firmas                      | Por la Secretaría: [Nombres y cargos]. Por el Proveedor: [Nombres, cargos, razón social]. |\n"
        "| Anexos                      | Número, nombre y descripción literal de cada anexo.                |\n"
        "| No localizado               | [Lista concreta de todo campo importante, dato o requisito legal que falte o esté incompleto. Si todo está, pon 'Ninguno.'] |\n"
        "| Áreas de mejora             | [Cada área de posible subjetividad, ambigüedad o riesgo de controversia. Si no hay, pon 'Ninguna.'] |\n"
        "\n"
        "LLENA CADA CAMPO CON SOLO LA INFORMACIÓN LITERAL DEL CONTRATO. NO CAMBIES EL FORMATO DE LA TABLA. "
        "Aquí está el texto del contrato:\n\n"
        + full_text
    )

    response_final = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Eres un experto en contratos públicos. Devuelve solo la tabla, siguiendo exactamente el formato y campos indicados, sin texto extra, sin contexto ni interpretaciones."},
            {"role": "user", "content": prompt_final}
        ],
        max_tokens=4096,
    )
    resultado = response_final.choices[0].message.content

    return resultado

@app.post("/analizar/")
async def analizar_contrato(
    file: UploadFile = File(...),
    x_api_key: str = Header(None),
    openai_key: str = Header(None, alias="openai-key")  # <-- Corrección aquí
):
    if x_api_key not in LICENSES:
        raise HTTPException(status_code=403, detail="Licencia no válida")
    if openai_key is None:
        raise HTTPException(status_code=401, detail="Debes enviar tu clave de OpenAI en el header 'openai-key'")

    contenido = await file.read()
    try:
        resultado = analizar_pdf_y_extraer_ficha(contenido, openai_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en análisis: {str(e)}")
    return {"usuario": LICENSES[x_api_key], "resultado": resultado}
"""Smart Home 5-Layer Backend Package.

Strict unidirectional dependency flow:
    api (Presentation HTTP adapter) -> strategy -> control -> device
    All layers access persistence strictly via data.repository interfaces.
"""

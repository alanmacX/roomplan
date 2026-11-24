// Usage: swift export-room.swift input.usdz output.js
import AppKit
import SceneKit

struct Mesh: Encodable {
    var name: String
    var furniture: Bool
    var color: [Double]
    var positions: [Float]
    var indices: [UInt32]
}

let args = CommandLine.arguments
guard args.count == 3 else { fatalError("expected USDZ input and JavaScript output") }
let scene = try SCNScene(url: URL(fileURLWithPath: args[1]), options: nil)
let root = scene.rootNode
var meshes: [Mesh] = []
root.enumerateChildNodes { node, _ in
    guard let geometry = node.geometry,
          let source = geometry.sources(for: .vertex).first,
          source.usesFloatComponents, source.bytesPerComponent == 4,
          source.componentsPerVector >= 3 else { return }
    let positions = source.data.withUnsafeBytes { data -> [Float] in
        (0..<source.vectorCount).flatMap { index -> [Float] in
            let i = source.dataOffset + source.dataStride * index
            let value = SCNVector3(
                data.loadUnaligned(fromByteOffset: i, as: Float.self),
                data.loadUnaligned(fromByteOffset: i + 4, as: Float.self),
                data.loadUnaligned(fromByteOffset: i + 8, as: Float.self)
            )
            let point = node.convertPosition(value, to: root)
            return [Float(point.x), Float(point.y), Float(point.z)]
        }
    }
    var parent: SCNNode? = node
    var furniture = false
    while let p = parent { if p.name == "Object_grp" { furniture = true; break }; parent = p.parent }
    for (index, element) in geometry.elements.enumerated() {
        guard element.primitiveType == .triangles else { fatalError("unexpected non-triangle mesh") }
        let indices = element.data.withUnsafeBytes { data -> [UInt32] in
            (0..<(element.primitiveCount * 3)).map { i -> UInt32 in
                let offset = i * element.bytesPerIndex
                switch element.bytesPerIndex {
                case 1: return UInt32(data.loadUnaligned(fromByteOffset: offset, as: UInt8.self))
                case 2: return UInt32(data.loadUnaligned(fromByteOffset: offset, as: UInt16.self))
                case 4: return data.loadUnaligned(fromByteOffset: offset, as: UInt32.self)
                default: fatalError("unexpected index width")
                }
            }
        }
        let raw = geometry.materials.indices.contains(index) ? geometry.materials[index].diffuse.contents : nil
        let color = (raw as? NSColor)?.usingColorSpace(.sRGB) ?? .white
        meshes.append(Mesh(name: node.name ?? "Mesh", furniture: furniture, color: [color.redComponent, color.greenComponent, color.blueComponent], positions: positions, indices: indices))
    }
}
guard !meshes.isEmpty else { fatalError("the USDZ contained no transferable meshes") }
let payload = try JSONEncoder().encode(meshes)
var output = Data("window.ROOMPLAN_MESHES = ".utf8)
output.append(payload)
output.append(Data(";\n".utf8))
try output.write(to: URL(fileURLWithPath: args[2]), options: .atomic)
print("\(meshes.count) meshes, \(meshes.reduce(0) { $0 + $1.indices.count / 3 }) triangles")

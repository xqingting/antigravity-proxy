// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "AntigravityProxyApp",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "AntigravityProxyApp", targets: ["AntigravityProxyApp"])
    ],
    targets: [
        .executableTarget(
            name: "AntigravityProxyApp",
            path: "Sources/AntigravityProxyApp"
        )
    ]
)

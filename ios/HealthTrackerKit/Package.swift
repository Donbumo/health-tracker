// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "HealthTrackerKit",
    defaultLocalization: "es",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "HealthTrackerKit", targets: ["HealthTrackerKit"]),
    ],
    targets: [
        .target(name: "HealthTrackerKit"),
        .testTarget(name: "HealthTrackerKitTests", dependencies: ["HealthTrackerKit"], resources: [.copy("Fixtures")]),
    ]
)

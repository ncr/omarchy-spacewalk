pragma Singleton
import QtQuick

// The plugin owns one service, shared by its widgets on every bar and monitor.
// Custom bars intentionally do not expose service objects through their facade.
QtObject {
  property var service: null
}

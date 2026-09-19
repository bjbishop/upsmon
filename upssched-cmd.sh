#!/bin/bash
case "$1" in
    onbatt-shutdown)
        logger -t upssched "10 minutes on battery reached — forcing OB LB"
        echo "OB LB" > /opt/upsmon/test-state
        ;;
    online)
        logger -t upssched "Power restored — cancelling shutdown timer and cleaning up"
        upssched -c cancel onbatt-shutdown
        rm -f /opt/upsmon/test-state
        ;;
esac

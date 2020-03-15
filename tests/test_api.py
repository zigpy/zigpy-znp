import pytest

import zigpy_znp.commands as cmds
from zigpy_znp.api import ZNP

@pytest.mark.asyncio
async def test_znp_responses():
    znp = ZNP()

    # Can't wait for non-response types
    with pytest.raises(ValueError):
        await znp.wait_for_response(cmds.sys.SysCommands.Ping.Req())

    response = cmds.sys.SysCommands.Ping.Rsp(Capabilities=cmds.types.MTCapabilities.CAP_SYS)
    future = znp.wait_for_response(cmds.sys.SysCommands.Ping.Rsp(partial=True))
    znp.frame_received(response.to_frame())
    
    assert (await future) == response

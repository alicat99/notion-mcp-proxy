from tool_runtime import UNSET, ToolRuntime


class NotionTools:
    """명시적인 Notion 도구 목록. 각 메서드를 수정해 도구별 정책을 추가한다."""

    def __init__(self, upstream, tools):
        self.runtime = ToolRuntime(upstream, tools, self, TOOL_METHODS)
        self.functions = self.runtime.functions

    #region Tools

    async def search(
        self, *,
        query,
        query_type=UNSET,
        data_source_url=UNSET,
        page_url=UNSET,
        teamspace_id=UNSET,
        filters=UNSET,
        sort=UNSET,
        page_size=UNSET,
        max_highlight_length=UNSET,
    ):
        """키워드와 필터로 콘텐츠 또는 사용자를 검색한다."""
        return await self.runtime.call("notion-search", {
            "query": query,
            "query_type": query_type,
            "data_source_url": data_source_url,
            "page_url": page_url,
            "teamspace_id": teamspace_id,
            "filters": filters,
            "sort": sort,
            "page_size": page_size,
            "max_highlight_length": max_highlight_length,
        })

    async def ai_search(
        self, *,
        query,
        data_source_url=UNSET,
        page_url=UNSET,
        teamspace_id=UNSET,
        page_size=UNSET,
        max_highlight_length=UNSET,
    ):
        """자연어로 Notion과 연결된 소스를 검색한다."""
        return await self.runtime.call("notion-ai-search", {
            "query": query,
            "data_source_url": data_source_url,
            "page_url": page_url,
            "teamspace_id": teamspace_id,
            "page_size": page_size,
            "max_highlight_length": max_highlight_length,
        })

    async def fetch(self, *, id, include_transcript=UNSET, include_discussions=UNSET):
        """페이지·데이터베이스·데이터 소스·뷰 또는 self 정보를 읽는다."""
        arguments = self.runtime.validate("notion-fetch", {
            "id": id,
            "include_transcript": include_transcript,
            "include_discussions": include_discussions,
        })
        return await self.runtime.permissions.fetch(arguments)

    async def create_attachment(
        self, *,
        filename=UNSET,
        content_type=UNSET,
        content=UNSET,
        source_url=UNSET,
        source_file_id=UNSET,
    ):
        """텍스트·외부 URL·업로드 ID로 첨부를 만든다."""
        return await self.runtime.call("notion-create-attachment", {
            "filename": filename,
            "content_type": content_type,
            "content": content,
            "source_url": source_url,
            "source_file_id": source_file_id,
        })

    async def create_file_upload(self, *, filename, content_type=UNSET):
        """로컬 파일을 전송할 업로드 URL을 발급한다."""
        return await self.runtime.call("notion-create-file-upload", {
            "filename": filename,
            "content_type": content_type,
        })

    async def download_attachment(self, *, file_upload_id):
        """작은 UTF-8 텍스트 첨부의 내용을 읽는다."""
        return await self.runtime.call("notion-download-attachment", {
            "file_upload_id": file_upload_id,
        })

    async def create_pages(self, *, pages, creation_mode=UNSET, parent=UNSET, allow_async=UNSET):
        """부모 위치와 속성·본문을 지정해 페이지들을 만든다."""
        arguments = self.runtime.validate("notion-create-pages", {
            "pages": pages,
            "creation_mode": creation_mode,
            "parent": parent,
            "allow_async": allow_async,
        })
        if "creation_mode" in arguments:
            raise PermissionError("Draft creation has no verified parent destination")
        await self.runtime.permissions.require_parent(arguments.get("parent"))
        return await self.runtime.call("notion-create-pages", arguments)

    async def update_page(
        self, *,
        page_id,
        command,
        properties=UNSET,
        new_str=UNSET,
        content=UNSET,
        content_updates=UNSET,
        position=UNSET,
        allow_deleting_content=UNSET,
        template_id=UNSET,
        verification_status=UNSET,
        verification_expiry_days=UNSET,
        icon=UNSET,
        cover=UNSET,
        is_skill=UNSET,
        allow_async=UNSET,
    ):
        """명령에 따라 페이지 속성·본문·아이콘 등을 수정한다."""
        arguments = self.runtime.validate("notion-update-page", {
            "page_id": page_id,
            "command": command,
            "properties": properties,
            "new_str": new_str,
            "content": content,
            "content_updates": content_updates,
            "position": position,
            "allow_deleting_content": allow_deleting_content,
            "template_id": template_id,
            "verification_status": verification_status,
            "verification_expiry_days": verification_expiry_days,
            "icon": icon,
            "cover": cover,
            "is_skill": is_skill,
            "allow_async": allow_async,
        })
        is_root = await self.runtime.permissions.require_target(page_id, {"page"})
        if is_root and arguments.get("properties"):
            # Ordinary root pages only support title properties; reject aliases as well.
            raise PermissionError("The allowed root's properties cannot be changed")
        return await self.runtime.call("notion-update-page", arguments)

    async def convert_page_to_skill(self, *, page_url):
        """기존 페이지를 Notion Skill로 지정한다."""
        return await self.runtime.call("notion-convert-page-to-skill", {
            "page_url": page_url,
        })

    async def search_skills(self, *, query=UNSET):
        """사용 가능한 Notion Skill을 검색한다."""
        return await self.runtime.call("notion-search-skills", {
            "query": query,
        })

    async def move_pages(self, *, page_or_database_ids, new_parent):
        """페이지 또는 데이터베이스들을 다른 부모로 이동한다."""
        arguments = self.runtime.validate("notion-move-pages", {
            "page_or_database_ids": page_or_database_ids,
            "new_parent": new_parent,
        })
        await self.runtime.permissions.require_parent(new_parent)
        for id in page_or_database_ids:
            await self.runtime.permissions.require_target(id, {"page", "database"}, allow_root=False)
        return await self.runtime.call("notion-move-pages", arguments)

    async def duplicate_page(self, *, page_id):
        """페이지를 복제하고 비동기 작업 정보를 반환한다."""
        return await self.runtime.call("notion-duplicate-page", {
            "page_id": page_id,
        })

    async def create_database(
        self, *,
        parent=UNSET,
        title=UNSET,
        description=UNSET,
        schema=UNSET,
        database_type=UNSET,
    ):
        """스키마나 데이터베이스 유형으로 데이터베이스를 만든다."""
        return await self.runtime.call("notion-create-database", {
            "parent": parent,
            "title": title,
            "description": description,
            "schema": schema,
            "database_type": database_type,
        })

    async def create_folder(self, *, parent, title):
        """페이지 또는 폴더 아래에 폴더를 만든다."""
        return await self.runtime.call("notion-create-folder", {
            "parent": parent,
            "title": title,
        })

    async def update_folder(
        self, *,
        folder_id,
        command,
        file_upload_ids=UNSET,
        file_urls=UNSET,
        title=UNSET,
    ):
        """명령에 따라 폴더의 파일이나 제목을 수정한다."""
        return await self.runtime.call("notion-update-folder", {
            "folder_id": folder_id,
            "command": command,
            "file_upload_ids": file_upload_ids,
            "file_urls": file_urls,
            "title": title,
        })

    async def update_data_source(
        self, *,
        data_source_id,
        statements=UNSET,
        title=UNSET,
        description=UNSET,
        is_inline=UNSET,
        in_trash=UNSET,
    ):
        """데이터 소스의 스키마·제목·속성을 수정한다."""
        return await self.runtime.call("notion-update-data-source", {
            "data_source_id": data_source_id,
            "statements": statements,
            "title": title,
            "description": description,
            "is_inline": is_inline,
            "in_trash": in_trash,
        })

    async def create_comment(
        self, *,
        page_id,
        discussion_id=UNSET,
        selection_with_ellipsis=UNSET,
        rich_text=UNSET,
        markdown=UNSET,
    ):
        """페이지에 댓글을 작성하거나 기존 토론에 답한다."""
        return await self.runtime.call("notion-create-comment", {
            "page_id": page_id,
            "discussion_id": discussion_id,
            "selection_with_ellipsis": selection_with_ellipsis,
            "rich_text": rich_text,
            "markdown": markdown,
        })

    async def get_comments(
        self, *,
        page_id,
        include_resolved=UNSET,
        include_all_blocks=UNSET,
        discussion_id=UNSET,
    ):
        """페이지의 댓글과 토론을 읽는다."""
        return await self.runtime.call("notion-get-comments", {
            "page_id": page_id,
            "include_resolved": include_resolved,
            "include_all_blocks": include_all_blocks,
            "discussion_id": discussion_id,
        })

    async def get_async_task(self, *, task_id):
        """Notion 비동기 작업의 현재 상태를 읽는다."""
        return await self.runtime.call("notion-get-async-task", {
            "task_id": task_id,
        })

    async def get_teams(self, *, query=UNSET):
        """워크스페이스의 팀스페이스를 조회한다."""
        return await self.runtime.call("notion-get-teams", {
            "query": query,
        })

    async def get_users(self, *, query=UNSET, start_cursor=UNSET, page_size=UNSET, user_id=UNSET):
        """워크스페이스의 사용자와 게스트를 조회한다."""
        return await self.runtime.call("notion-get-users", {
            "query": query,
            "start_cursor": start_cursor,
            "page_size": page_size,
            "user_id": user_id,
        })

    async def query_data_sources(self, *, data):
        """중첩 data 객체의 모드에 따라 행·SQL·뷰를 조회한다."""
        return await self.runtime.call("notion-query-data-sources", {
            "data": data,
        })

    async def query_multiple_data_sources(self, *, query, data_source_urls, params=UNSET, mode=UNSET):
        """여러 데이터 소스를 읽기 전용 SQL로 조회한다. 서버가 노출하는 기존 도구다."""
        return await self.runtime.call("notion-query-multiple-data-sources", {
            "query": query,
            "data_source_urls": data_source_urls,
            "params": params,
            "mode": mode,
        })

    async def query_meeting_notes(self, *, filter=UNSET):
        """현재 사용자의 회의록을 필터링해 조회한다."""
        return await self.runtime.call("notion-query-meeting-notes", {
            "filter": filter,
        })

    async def list_private_pages(self, *, limit=UNSET, cursor=UNSET):
        """개인 사이드바의 최상위 페이지와 데이터베이스를 조회한다."""
        return await self.runtime.call("notion-list-private-pages", {
            "limit": limit,
            "cursor": cursor,
        })

    async def list_shared_pages(self, *, limit=UNSET, cursor=UNSET):
        """공유 사이드바의 페이지와 데이터베이스를 조회한다."""
        return await self.runtime.call("notion-list-shared-pages", {
            "limit": limit,
            "cursor": cursor,
        })

    async def list_favorite_pages(self, *, limit=UNSET, cursor=UNSET):
        """즐겨찾는 페이지와 데이터베이스를 조회한다."""
        return await self.runtime.call("notion-list-favorite-pages", {
            "limit": limit,
            "cursor": cursor,
        })

    async def list_recent_pages(self, *, limit=UNSET, cursor=UNSET):
        """최근 방문한 페이지와 데이터베이스를 조회한다."""
        return await self.runtime.call("notion-list-recent-pages", {
            "limit": limit,
            "cursor": cursor,
        })

    async def search_agents(self, *, scope, query=UNSET, limit=UNSET, cursor=UNSET):
        """Custom Agent를 검색하거나 범위에 따라 목록을 조회한다."""
        return await self.runtime.call("notion-search-agents", {
            "scope": scope,
            "query": query,
            "limit": limit,
            "cursor": cursor,
        })

    async def search_sessions(self, *, question, lookback=UNSET):
        """주제와 기간으로 과거 에이전트 세션을 검색한다."""
        return await self.runtime.call("notion-search-sessions", {
            "question": question,
            "lookback": lookback,
        })

    async def query_sessions(
        self, *,
        query=UNSET,
        filter=UNSET,
        sorts=UNSET,
        start_cursor=UNSET,
        page_size=UNSET,
    ):
        """필터·정렬·제목 검색으로 에이전트 세션을 조회한다."""
        return await self.runtime.call("notion-query-sessions", {
            "query": query,
            "filter": filter,
            "sorts": sorts,
            "start_cursor": start_cursor,
            "page_size": page_size,
        })

    async def spawn_session(self, *, agent_url, initial_message):
        """공개된 Custom Agent의 새 세션을 시작한다."""
        return await self.runtime.call("notion-spawn-session", {
            "agent_url": agent_url,
            "initial_message": initial_message,
        })

    async def get_session_status(self, *, session_url):
        """에이전트 세션의 최신 상태를 읽는다."""
        return await self.runtime.call("notion-get-session-status", {
            "session_url": session_url,
        })

    async def wait_session(self, *, session_url, seconds):
        """에이전트 세션이 멈추거나 완료될 때까지 지정 시간 동안 기다린다."""
        return await self.runtime.call("notion-wait-session", {
            "session_url": session_url,
            "seconds": seconds,
        })

    async def stop_session(self, *, session_url):
        """실행 중인 에이전트 세션을 중지한다."""
        return await self.runtime.call("notion-stop-session", {
            "session_url": session_url,
        })

    async def send_message_to_session(self, *, session_url, message):
        """에이전트 세션에 후속 메시지를 보낸다."""
        return await self.runtime.call("notion-send-message-to-session", {
            "session_url": session_url,
            "message": message,
        })

    async def list_session_events(
        self, *,
        session_url,
        count,
        before_sequence=UNSET,
        after_sequence=UNSET,
    ):
        """세션에 저장된 이벤트의 요약 목록을 읽는다."""
        return await self.runtime.call("notion-list-session-events", {
            "session_url": session_url,
            "count": count,
            "before_sequence": before_sequence,
            "after_sequence": after_sequence,
        })

    async def read_session_event(self, *, session_url, sequence):
        """세션의 특정 이벤트 내용을 읽는다."""
        return await self.runtime.call("notion-read-session-event", {
            "session_url": session_url,
            "sequence": sequence,
        })

    async def create_view(
        self, *,
        data_source_id,
        name,
        type,
        database_id=UNSET,
        parent_page_id=UNSET,
        configure=UNSET,
    ):
        """데이터베이스에 유형과 구성을 지정한 뷰를 만든다."""
        return await self.runtime.call("notion-create-view", {
            "data_source_id": data_source_id,
            "name": name,
            "type": type,
            "database_id": database_id,
            "parent_page_id": parent_page_id,
            "configure": configure,
        })

    async def update_view(self, *, view_id, name=UNSET, configure=UNSET):
        """뷰의 이름과 필터·정렬·표시 구성을 수정한다."""
        return await self.runtime.call("notion-update-view", {
            "view_id": view_id,
            "name": name,
            "configure": configure,
        })

    async def show_advanced_analysis_next_steps(self):
        """고급 분석 사용을 위한 다음 단계 안내를 조회한다."""
        return await self.runtime.call("notion-show-advanced-analysis-next-steps", {})

    async def check_mcp_next_steps(self):
        """Notion MCP 사용에 대한 다음 단계 안내를 조회한다."""
        return await self.runtime.call("notion-check-mcp-next-steps", {})

    #endregion

TOOL_METHODS = {
    "notion-search": "search",
    "notion-ai-search": "ai_search",
    "notion-fetch": "fetch",
    "notion-create-attachment": "create_attachment",
    "notion-create-file-upload": "create_file_upload",
    "notion-download-attachment": "download_attachment",
    "notion-create-pages": "create_pages",
    "notion-update-page": "update_page",
    "notion-convert-page-to-skill": "convert_page_to_skill",
    "notion-search-skills": "search_skills",
    "notion-move-pages": "move_pages",
    "notion-duplicate-page": "duplicate_page",
    "notion-create-database": "create_database",
    "notion-create-folder": "create_folder",
    "notion-update-folder": "update_folder",
    "notion-update-data-source": "update_data_source",
    "notion-create-comment": "create_comment",
    "notion-get-comments": "get_comments",
    "notion-get-async-task": "get_async_task",
    "notion-get-teams": "get_teams",
    "notion-get-users": "get_users",
    "notion-query-data-sources": "query_data_sources",
    "notion-query-multiple-data-sources": "query_multiple_data_sources",
    "notion-query-meeting-notes": "query_meeting_notes",
    "notion-list-private-pages": "list_private_pages",
    "notion-list-shared-pages": "list_shared_pages",
    "notion-list-favorite-pages": "list_favorite_pages",
    "notion-list-recent-pages": "list_recent_pages",
    "notion-search-agents": "search_agents",
    "notion-search-sessions": "search_sessions",
    "notion-query-sessions": "query_sessions",
    "notion-spawn-session": "spawn_session",
    "notion-get-session-status": "get_session_status",
    "notion-wait-session": "wait_session",
    "notion-stop-session": "stop_session",
    "notion-send-message-to-session": "send_message_to_session",
    "notion-list-session-events": "list_session_events",
    "notion-read-session-event": "read_session_event",
    "notion-create-view": "create_view",
    "notion-update-view": "update_view",
    "notion-show-advanced-analysis-next-steps": "show_advanced_analysis_next_steps",
    "notion-check-mcp-next-steps": "check_mcp_next_steps",
}

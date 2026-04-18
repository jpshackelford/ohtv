import pytest
from ohtv.prompts.metadata import EventFilter, ContextLevel, PromptMetadata


class TestEventFilter:
    """Tests for EventFilter.matches()"""
    
    def test_wildcard_matches_everything(self):
        """Test that default wildcard filter matches any event"""
        f = EventFilter()
        assert f.matches({"source": "user", "kind": "MessageEvent"})
        assert f.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "finish"})
        assert f.matches({"source": "user", "kind": "ErrorEvent"})
    
    def test_source_filter(self):
        """Test filtering by source"""
        f = EventFilter(source="user")
        assert f.matches({"source": "user", "kind": "MessageEvent"})
        assert not f.matches({"source": "agent", "kind": "MessageEvent"})
    
    def test_kind_filter(self):
        """Test filtering by kind"""
        f = EventFilter(kind="MessageEvent")
        assert f.matches({"source": "user", "kind": "MessageEvent"})
        assert not f.matches({"source": "user", "kind": "ActionEvent", "tool_name": "terminal"})
    
    def test_tool_filter_requires_action_event(self):
        """Test that tool filter only matches ActionEvent"""
        f = EventFilter(tool="finish")
        assert not f.matches({"source": "agent", "kind": "MessageEvent", "tool_name": "finish"})
        assert f.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "finish"})
    
    def test_tool_filter_with_specific_tool(self):
        """Test that tool filter matches specific tool name"""
        f = EventFilter(tool="terminal")
        assert f.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "terminal"})
        assert not f.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "finish"})
    
    def test_combined_filters(self):
        """Test combining multiple filter criteria"""
        f = EventFilter(source="agent", kind="ActionEvent", tool="terminal")
        assert f.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "terminal"})
        assert not f.matches({"source": "user", "kind": "ActionEvent", "tool_name": "terminal"})
        assert not f.matches({"source": "agent", "kind": "MessageEvent", "tool_name": "terminal"})
        assert not f.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "finish"})
    
    def test_wildcard_source_with_specific_kind(self):
        """Test wildcard source with specific kind"""
        f = EventFilter(source="*", kind="MessageEvent")
        assert f.matches({"source": "user", "kind": "MessageEvent"})
        assert f.matches({"source": "agent", "kind": "MessageEvent"})
        assert not f.matches({"source": "user", "kind": "ActionEvent", "tool": "finish"})


class TestContextLevel:
    """Tests for ContextLevel.matches()"""
    
    def test_include_any_matches(self):
        """Test that ANY include filter matching causes inclusion"""
        ctx = ContextLevel(
            number=1,
            name="test",
            include=[
                EventFilter(kind="MessageEvent"),
                EventFilter(kind="ErrorEvent")
            ]
        )
        assert ctx.matches({"source": "user", "kind": "MessageEvent"})
        assert ctx.matches({"source": "agent", "kind": "ErrorEvent"})
        assert not ctx.matches({"source": "agent", "kind": "ActionEvent", "tool": "finish"})
    
    def test_exclude_overrides_include(self):
        """Test that exclude filters override include filters"""
        ctx = ContextLevel(
            number=1,
            name="test",
            include=[EventFilter()],  # Match everything
            exclude=[EventFilter(kind="ActionEvent")]
        )
        assert ctx.matches({"source": "user", "kind": "MessageEvent"})
        assert not ctx.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "finish"})
    
    def test_no_include_matches_means_no_match(self):
        """Test that if no include filter matches, event is excluded"""
        ctx = ContextLevel(
            number=1,
            name="test",
            include=[EventFilter(kind="MessageEvent")]
        )
        assert not ctx.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "finish"})
    
    def test_specific_tool_inclusion(self):
        """Test including only specific tool actions"""
        ctx = ContextLevel(
            number=1,
            name="test",
            include=[EventFilter(kind="ActionEvent", tool="finish")]
        )
        assert ctx.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "finish"})
        assert not ctx.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "terminal"})
    
    def test_complex_include_exclude(self):
        """Test complex include/exclude combination"""
        ctx = ContextLevel(
            number=2,
            name="selective",
            include=[
                EventFilter(kind="MessageEvent"),
                EventFilter(kind="ActionEvent")
            ],
            exclude=[
                EventFilter(kind="ActionEvent", tool="terminal")
            ]
        )
        assert ctx.matches({"source": "user", "kind": "MessageEvent"})
        assert ctx.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "finish"})
        assert not ctx.matches({"source": "agent", "kind": "ActionEvent", "tool_name": "terminal"})


class TestPromptMetadata:
    """Tests for PromptMetadata.get_context_level()"""
    
    def test_get_context_level_by_number(self):
        """Test getting context level by number"""
        ctx1 = ContextLevel(1, "minimal", [EventFilter()])
        ctx2 = ContextLevel(2, "full", [EventFilter()])
        meta = PromptMetadata(
            id="test.brief",
            family="test",
            variant="brief",
            context_levels={1: ctx1, 2: ctx2}
        )
        assert meta.get_context_level(1) == ctx1
        assert meta.get_context_level(2) == ctx2
    
    def test_get_context_level_by_name(self):
        """Test getting context level by name"""
        ctx1 = ContextLevel(1, "minimal", [EventFilter()])
        ctx2 = ContextLevel(2, "full", [EventFilter()])
        meta = PromptMetadata(
            id="test.brief",
            family="test",
            variant="brief",
            context_levels={1: ctx1, 2: ctx2}
        )
        assert meta.get_context_level("minimal") == ctx1
        assert meta.get_context_level("full") == ctx2
    
    def test_get_context_level_unknown_number(self):
        """Test that unknown number raises ValueError"""
        meta = PromptMetadata(
            id="test.brief",
            family="test",
            variant="brief",
            context_levels={}
        )
        with pytest.raises(ValueError, match="Unknown context level: 1"):
            meta.get_context_level(1)
    
    def test_get_context_level_unknown_name(self):
        """Test that unknown name raises ValueError"""
        meta = PromptMetadata(
            id="test.brief",
            family="test",
            variant="brief",
            context_levels={}
        )
        with pytest.raises(ValueError, match="Unknown context level: minimal"):
            meta.get_context_level("minimal")

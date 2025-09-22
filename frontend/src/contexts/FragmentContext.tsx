"use client";

import React, { createContext, useContext, useState, useCallback } from 'react';

type FragmentState = {
  isVisible: boolean;
  id?: string;
  title?: string;
  content: string;
  language?: string;
  path?: string;
};

type FragmentContextType = FragmentState & {
  openFragment: (params: { id: string; title?: string; content: string; language?: string; path?: string }) => void;
  closeFragment: () => void;
  updateContent: (content: string) => void;
};

const FragmentContext = createContext<FragmentContextType | null>(null);

export function FragmentProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<FragmentState>({
    isVisible: false,
    content: '',
  });

  const openFragment = useCallback((params: { id: string; title?: string; content: string; language?: string; path?: string }) => {
    setState({
      isVisible: true,
      id: params.id,
      title: params.title,
      content: params.content,
      language: params.language,
      path: params.path,
    });
  }, []);

  const closeFragment = useCallback(() => {
    setState({
      isVisible: false,
      content: '',
      id: undefined,
      title: undefined,
      language: undefined,
      path: undefined,
    });
  }, []);

  const updateContent = useCallback((content: string) => {
    setState(prev => ({ ...prev, content }));
  }, []);

  return (
    <FragmentContext.Provider value={{
      ...state,
      openFragment,
      closeFragment,
      updateContent,
    }}>
      {children}
    </FragmentContext.Provider>
  );
}

export const useFragment = () => {
  const context = useContext(FragmentContext);
  if (!context) {
    throw new Error('useFragment must be used within a FragmentProvider');
  }
  return context;
};